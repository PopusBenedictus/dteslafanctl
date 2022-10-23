from datetime import datetime, timedelta
from numpy import geomspace
from signal import signal, SIGINT
from subprocess import Popen, PIPE, STDOUT
from threading import Thread, Event
from queue import Queue
from time import sleep
import argparse
import subprocess

runtime_params = {
    'gpu_max_temp_threshold': 80,
    'gpu_min_fan_speed_target': 50,
    'gpu_idle_temp_target': 45,
    'gpu_auto_handoff_interval': 10,
    'gpu_idle_condition_threshold': 0,
    'gpu_activate_fan_control_threshold': -1,
    'ignore_gpus': None
}

raw_lines = Queue()
stop_nvidia_smi = Event()
complete_shutdown = False


def use_which(program_name: str) -> bool:
    if subprocess.call(['which', program_name], stdout=PIPE) == 0:
        return True
    else:
        return False


def check_dependencies() -> bool:
    tools = ['ipmitool', 'nvidia-smi']
    for tool in tools:
        if not use_which(tool):
            print(f"Cannot locate dependency: {tool} -- aborting.")
            return False

    return True


def get_arg_parser(d: dict) -> argparse.ArgumentParser():
    new_parser = argparse.ArgumentParser(description="Enables GPU load responsive automatic fan control in "
                                                     "Dell R series servers from the mid 2010's and later. Only "
                                                     "supports NVIDIA graphics cards. Specifically intended for "
                                                     "Tesla series graphics cards without onboard cooling.",
                                         epilog="Your goal should always be to have dteslafanctl disengage and return "
                                                "control of the system fans back to the BMC when your GPU's are idle. "
                                                "Otherwise your system may not be able to respond to other cooling "
                                                "demands adequately, specifically your CPU's.")

    new_parser.add_argument('--gpu-max-temp-threshold',
                            action='store',
                            type=int,
                            required=False,
                            help="GPU temperature (in celsius) that invokes 100%% fan output response "
                                 f"(Default: {d['gpu_max_temp_threshold']}).")

    new_parser.add_argument('--gpu-min-fan-speed-target',
                            action='store',
                            type=int,
                            required=False,
                            help="The minimum fan speed (in percentage) used to calculate our fan speed curve. "
                                 "This correlates with the GPU idle temperature target such that the fans will "
                                 "not spin any slower than this unless the fans are slowed down when control is "
                                 "handed off to the BMC. You probably want this to be 10-15%% faster than the nominal "
                                 "idle speed the BMC sets your fans to without external intervention. This will get "
                                 "your GPU(s) down to idle temperature sooner and thus allow automatic handoff to "
                                 f"occur sooner. (Default: {d['gpu_min_fan_speed_target']}).")

    new_parser.add_argument('--gpu-idle-temp-target',
                            action='store',
                            type=int,
                            required=False,
                            help="GPU temperature (under idle conditions) that starts the handoff to "
                                 f"auto fan control (Default: {d['gpu_idle_temp_target']}).")

    new_parser.add_argument('--gpu-auto-handoff-interval',
                            action='store',
                            type=int,
                            required=False,
                            help="When GPU idle conditions at or below target idle temperature are achieved, "
                                 "this how long, in seconds, dteslafanctl should wait before handing fan "
                                 f"control back to the BMC (Default: {d['gpu_auto_handoff_interval']}).")

    new_parser.add_argument('--gpu-idle-condition-threshold',
                            action='store',
                            type=int,
                            required=False,
                            help="Dictates the threshold (in GPU utilization percentage) for what is considered "
                                 "idle usage of the GPU. Adjust this if your workloads always place some residual "
                                 f"load on the GPU at all times (Default: {d['gpu_idle_condition_threshold']}).")

    new_parser.add_argument('--gpu-activate-fan-control-threshold',
                            action='store',
                            type=int,
                            required=False,
                            help="Dictates the threshold (in GPU temperature (celsius)) for when to take control of "
                                 "the fans from the BMC. (Default is ten degrees celsius above the target idle "
                                 "temperature threshold, but this value is considered absolute. Meaning if 50 were "
                                 "specified as the value, the activation threshold is 50 degrees celsius).")

    new_parser.add_argument('--ignore-gpus',
                            action='store',
                            type=str,
                            help="One or more GPU's (by index as reported by nvidia-smi) whose temperatures should be "
                                 "ignored completely. Useful if you have multiple GPU's installed but one or more of "
                                 "them have cooling solutions independent of the server's internal cooling. "
                                 "You can specify one index alone (e.g. --ignore-gpus 0) or comma separated values "
                                 "(e.g. --ignore-gpus 0,1) (Default: None).")

    return new_parser


def nvidia_smi_runner():
    print("Starting Nvidia SMI listening loop.")
    p = Popen(['nvidia-smi',
               '--query-gpu=index,gpu_name,temperature.gpu,utilization.gpu',
               '--format=csv,noheader,nounits',
               '-l', '3'], stdout=PIPE)

    result = p.poll()
    while result is None and not stop_nvidia_smi.isSet():
        raw_lines.put(p.stdout.readline().decode('utf-8'))
        result = p.poll()
        sleep(0.25)

    print("Stopping Nvidia SMI listening loop.")
    p.kill()
    if not stop_nvidia_smi.isSet():
        for line in p.stdout.readlines():
            raw_lines.put(line)

    print("Signaling for shutdown completion")
    global complete_shutdown
    complete_shutdown = True


def sigint_handler(signal_received, frame):
    print("SIGINT received, shutting down.")
    stop_nvidia_smi.set()


def ipmi_toggle_fan_control(enable_manual_control: bool) -> bool:
    result = None
    if enable_manual_control:
        result = subprocess.call(['ipmitool', 'raw', '0x30', '0x30', '0x01', '0x00'], stdout=PIPE)
    else:
        result = subprocess.call(['ipmitool', 'raw', '0x30', '0x30', '0x01', '0x01'], stdout=PIPE)

    return True if result == 0 else False


def ipmi_set_static_fan_speed(levels: dict, temperature: int) -> bool:
    temp = next(filter(lambda k: temperature <= int(k), levels), None)

    if temp is None:
        speed = list(levels.items())[-1][1]
    else:
        speed = levels[temp]

    result = subprocess.call(['ipmitool', 'raw', '0x30', '0x30', '0x02', '0xff', f"0x{int(speed):02X}"], stdout=PIPE)
    return True if result == 0 else False


if __name__ == '__main__':
    signal(SIGINT, sigint_handler)
    if not check_dependencies():
        exit(1)

    args = get_arg_parser(runtime_params).parse_args()
    for a in vars(args):
        if vars(args)[a] is not None:
            runtime_params[a] = vars(args)[a]

    if runtime_params['gpu_activate_fan_control_threshold'] == -1:
        runtime_params['gpu_activate_fan_control_threshold'] = runtime_params['gpu_idle_temp_target'] + 10

    ignored_gpus = []
    if runtime_params['ignore_gpus'] is not None:
        gpus = runtime_params['ignore_gpus'].split(',')
        for gpu in gpus:
            ignored_gpus.append(gpu.strip(' '))

    t = Thread(target=nvidia_smi_runner)
    t.start()

    manual_activated_dt = None
    manual_met_idle_temp_dt = None
    temp_levels = geomspace(start=runtime_params['gpu_activate_fan_control_threshold'],
                            stop=runtime_params['gpu_max_temp_threshold'],
                            num=512)

    fan_levels = geomspace(start=runtime_params['gpu_min_fan_speed_target'],
                           stop=100.0,
                           num=512)

    levels_dict = {}
    i = 0
    while i < 512:
        levels_dict[temp_levels[i]] = fan_levels[i]
        i += 1

    # When we have no new data to look at, stores previous highest values and sets current high values to these.
    previous_util = 0
    previous_temp = 0
    previous_idx = 0
    previous_name = ""

    while not complete_shutdown:
        highest_util = 0
        highest_temp = 0
        highest_idx = 0
        highest_name = ""

        if raw_lines.empty():
            highest_util = previous_util
            highest_temp = previous_temp
            highest_idx = previous_idx
            highest_name = previous_name
        else:
            while not raw_lines.empty():
                raw_data = raw_lines.get().split(',')
                clean_data = []

                for rdi in raw_data:
                    clean_data.append(rdi.strip(' \n'))

                if ignored_gpus is not None and clean_data[0] in ignored_gpus:
                    continue

                if int(clean_data[2]) > highest_temp:
                    highest_idx = int(clean_data[0])
                    highest_name = clean_data[1]
                    highest_temp = int(clean_data[2])
                    highest_util = int(clean_data[3])

                previous_util = highest_util
                previous_temp = highest_temp
                previous_idx = highest_idx
                previous_name = highest_name

        if manual_activated_dt is None and highest_temp >= runtime_params['gpu_activate_fan_control_threshold']:
            manual_activated_dt = datetime.now()
            print(f"dteslafanctl: took fan control over on {manual_activated_dt} "
                  f"for card {highest_name} (id: {highest_idx})")
            manual_met_idle_temp_dt = None
            if not ipmi_toggle_fan_control(True):
                print("dteslafanctl: could not take control of fan speed from Dell BMC")
                stop_nvidia_smi.set()
        elif manual_activated_dt is not None and manual_met_idle_temp_dt is None and \
                highest_temp <= runtime_params['gpu_idle_temp_target']:
            print(f"dteslafanctl: idle temperature threshold reached")
            manual_met_idle_temp_dt = datetime.now()
        elif manual_met_idle_temp_dt is not None:
            if (datetime.now() - manual_met_idle_temp_dt).total_seconds() >= \
                    runtime_params['gpu_auto_handoff_interval'] and highest_util <= \
                    runtime_params['gpu_idle_condition_threshold']:
                print(f"dteslafanctl: handing fan control back to Dell BMC")
                if not ipmi_toggle_fan_control(False):
                    print("dteslafanctl: WARNING -- COULD NOT RETURN FAN CONTROL BACK TO DELL BMC")
                    stop_nvidia_smi.set()

                manual_activated_dt = None
                manual_met_idle_temp_dt = None

        if manual_activated_dt is not None:
            if not ipmi_set_static_fan_speed(levels_dict, highest_temp):
                print("dteslafanctl: error setting fan speed through manual control")
                stop_nvidia_smi.set()

        sleep(1)

    if ipmi_toggle_fan_control(False):
        print("dteslafanctl: returned automatic fan control back to Dell BMC")
        exit(0)
    else:
        print("dteslafanctl: WARNING -- COULD NOT RETURN FAN CONTROL BACK TO DELL BMC")
        exit(1)
