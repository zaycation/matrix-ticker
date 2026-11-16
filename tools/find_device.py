"""List USB HID devices so you can spot the Matrix panel (run on Windows).

    pip install hidapi
    python tools/find_device.py

If the panel does NOT show up here, it's a vendor-class (bulk) device, not HID.
Check with PowerShell instead:
    Get-PnpDevice -PresentOnly | ? InstanceId -like 'USB\\VID*' | ft FriendlyName,InstanceId
"""
import hid

for d in hid.enumerate():
    print(f"{d['vendor_id']:04x}:{d['product_id']:04x}  "
          f"usage_page=0x{d['usage_page']:04x} usage=0x{d['usage']:02x} "
          f"iface={d['interface_number']}  "
          f"{d['manufacturer_string']!r} {d['product_string']!r}\n    {d['path']!r}")
