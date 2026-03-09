#!/bin/bash
# gameplayer-bot USB HID composite gadget setup
# Creates a composite USB device with keyboard + mouse HID functions.
# Installed to /usr/local/bin/gameplayer-bot-gadget.sh by setup.sh
# Runs at boot via gameplayer-bot-gadget.service

set -e

GADGET_DIR=/sys/kernel/config/usb_gadget/gameplayer-bot

# Exit if already configured
if [ -d "$GADGET_DIR" ]; then
    echo "gameplayer-bot gadget already configured"
    exit 0
fi

# Create gadget
mkdir -p "$GADGET_DIR"
cd "$GADGET_DIR"

# Device descriptor
echo 0x1d6b > idVendor   # Linux Foundation
echo 0x0104 > idProduct   # Multifunction Composite Gadget
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

# Device strings
mkdir -p strings/0x409
echo "gameplayer-bot-01" > strings/0x409/serialnumber
echo "gameplayer-bot"    > strings/0x409/manufacturer
echo "gameplayer-bot"    > strings/0x409/product

# --- HID Keyboard Function ---
mkdir -p functions/hid.keyboard
echo 1 > functions/hid.keyboard/protocol    # 1 = keyboard
echo 1 > functions/hid.keyboard/subclass    # 1 = boot interface
echo 8 > functions/hid.keyboard/report_length

# Standard boot keyboard report descriptor (63 bytes)
echo -ne '\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x01\x95\x05\x75\x01\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x01\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0' \
    > functions/hid.keyboard/report_desc

# --- HID Mouse Function ---
mkdir -p functions/hid.mouse
echo 2 > functions/hid.mouse/protocol      # 2 = mouse
echo 1 > functions/hid.mouse/subclass      # 1 = boot interface
echo 4 > functions/hid.mouse/report_length

# Boot mouse report descriptor: 3 buttons + dx + dy (relative)
echo -ne '\x05\x01\x09\x02\xa1\x01\x09\x01\xa1\x00\x05\x09\x19\x01\x29\x03\x15\x00\x25\x01\x75\x01\x95\x03\x81\x02\x75\x05\x95\x01\x81\x01\x05\x01\x09\x30\x09\x31\x15\x81\x25\x7f\x75\x08\x95\x02\x81\x06\xc0\xc0' \
    > functions/hid.mouse/report_desc

# --- Configuration ---
mkdir -p configs/c.1/strings/0x409
echo "gameplayer-bot Config" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower  # 250 x 2mA = 500mA

# Link functions to configuration
ln -s functions/hid.keyboard configs/c.1/
ln -s functions/hid.mouse    configs/c.1/

# Bind to UDC (USB Device Controller)
UDC=$(ls /sys/class/udc | head -1)
if [ -z "$UDC" ]; then
    echo "ERROR: No USB Device Controller found. Is dwc2 overlay enabled?"
    exit 1
fi
echo "$UDC" > UDC

echo "gameplayer-bot gadget configured: keyboard=/dev/hidg0 mouse=/dev/hidg1"
