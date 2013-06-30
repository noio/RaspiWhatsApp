#/usr/bin/env bash

# Some things I had to fix in order to get this running on a 
# clean Raspberry Pi.

# - Run `sudo dpkg-reconfigure locales` to fix the locales issue. Install 'en-US UTF-8' and set as default.
# - apt-get install screen.
# - Clone raspi whatsapp repo (https://github.com/noio/RaspiWhatsApp.git)
# - Get easy_install (setuptools) for Python:
    
#     wget https://bitbucket.org/pypa/setuptools/raw/0.7.4/ez_setup.py -O - | sudo python

# - `sudo easy_install pip`
# - `sudo pip install pyusb`
# - `sudo apt-get install python-dev`
# - `sudo pip install PIL`
# - Get some tea
# - `git submodule update --init` in the repo directory to get yowsup and python-escpos
# - `sudo pip install pyserial`
# - `sudo pip install python-dateutil`

# When this is all done:

# http://raspberrypi.stackexchange.com/questions/311/how-do-i-backup-my-raspberry-pi

##### DOING IT AUTOMATICALLY #####
# First, still run `sudo dpkg-reconfigure locales` to fix the locales issue. Install 'en-US UTF-8' and set as default.

git submodule update --init
sudo apt-get update
sudo apt-get -y install screen python-dev 
sudo apt-get install libjpeg8 libjpeg62-dev libfreetype6 libfreetype6-dev
sudo apt-get install python-imaging
sudo ln -s /usr/lib/arm-linux-gnueabihf/libfreetype.so /usr/lib/
sudo ln -s /usr/lib/arm-linux-gnueabihf/libz.so /usr/lib/
sudo ln -s /usr/lib/arm-linux-gnueabihf/libjpeg.so /usr/lib/
wget https://bitbucket.org/pypa/setuptools/raw/0.7.4/ez_setup.py -O - | sudo python
curl -O https://raw.github.com/pypa/pip/master/contrib/get-pip.py
sudo python get-pip.py
sudo pip install pyusb PIL pyserial python-dateutil numpy