# Dell System Fan Controller for Nvidia Tesla et. al. GPU Owners

## Summary
This script can be used on **Linux** servers to help your Dell R series (think R720, R730, etc.) server 
respond to cooling demands that unsupported Nvidia graphics hardware may demand. Specifically, this is 
intended to be used with unsupported Tesla graphics cards that do not have their own fans for cooling.

It activates based on either default or user provided thresholds, taking manual control over the fans and 
using IPMI on the host to steer their speed around as needed. When your graphics hardware returns to 
an idle state, it forfeits control over the fan back to the server. This is necessary to allow the system 
to respond to cooling demands by other components of the system, like the CPU's.

## Caveat Emptor -- Use at Your Own Risk
This script enables you to do something that Dell definitely does not support and I am in no way 
able to confirm will be safe for your given application. I am not responsible for any damage you do 
to your system, your house, your pets, I am not liable for any harm that you bestow upon yourself using 
this tool.

Do your research and make sure your server can support any aftermarket hardware you add to it before you 
commit to it. Graphics hardware, especially enterprise graphics hardware, is extremely demanding and 
some configurations may allow you to slap hardware in on a theoretical basis, but in reality might not 
be able to support the demands or cause instability or hazards you may not have considered. You have been 
warned!

## Prerequisites
You'll need the following sorted before you run this script.
* Python 3.9 or later.
* The `numpy` python package (e.g. `pip install numpy`)
* These command line tools: `nvidia-smi`, `which`, `ipmitool`
  * The first tool is typically made available after installing proprietary Nvidia graphics drivers.
  * The `which` tool is usually available with base packages installed by your distribution but can 
    otherwise be found as its own package.
  * The last is usually coupled with a package named thereabout `ipmi-tools` or similar.
  * Use a search engine -- I believe in you, random internet stranger. :)
* You may need to enable IPMI in your iDRAC.

I don't specifically offer it here, but you could probably wrap this up in a basic systemctl 
service. Or a sysvinit service. I don't have time to support this for any particular distribution 
so you're on your own, friend.

## Usage
You can simply run it without any arguments, accepting the default parameters. If you'd like 
to see the tunables, simply pass `-h` without any other arguments (e.g. `python main.py -h`)

**It is really important that you have sane idle temperature thresholds so that the server can 
take control over the fans when your graphics hardware is not doing any work.** Otherwise, it's possible 
this script will prevent the server from ramping the fans up in response to high loads elsewhere, such 
as your CPU's. Causing thermal issues elsewhere where you did not intend there to be.

The script uses data from all Nvidia graphics cards provided and works off the data from the 
spiciest of your cards to set the fan speed. You can use the `--ignore-gpus` parameter to 
specify one or more (comma-separated) cards by their index value as represented in `nvidia-smi`. 
This is called out in the help dialog, but I figured I should call it out directly incase you have 
multiple cards and one is not inside the chassis.