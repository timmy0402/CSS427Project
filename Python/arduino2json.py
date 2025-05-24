import json 
import asyncio
import io
from bleak import BleakScanner, BleakClient
from jsonbuffer import get_shared_data
shared_data = get_shared_data()


SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

async def main():
    buffer = io.BytesIO()
    print("Scanning for UNO_R4_UART...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, ad: d.name and "UNO_R4_UART" in d.name
    )
    if not device:
        print("Device not found.")
        return

    async with BleakClient(device) as client:
        print("Connected to", device.address)

        def on_rx(_, data):
            print("From Arduino:", data.decode().strip())
            try:
                json_data = json.loads(data.decode().strip())
                print("Parsed JSON:", json_data)
                shared_data.append(json_data)
            except json.JSONDecodeError:
                print("Failed to decode JSON")
            

        await client.start_notify(TX_UUID, on_rx)

        while True:
            await asyncio.sleep(1)

asyncio.run(main())
