import dash
from dash import dcc
from dash import html
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import numpy as np
import random
from bleak import BleakScanner, BleakClient
import asyncio
import threading

SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

app = dash.Dash(__name__)
x = [0, 1]
y = [1, 1]
z = [1, 1]


async def run_ble():
    print("Scanning for UNO_R4_UART...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, ad: d.name and "UNO_R4_UART" in d.name)
    if not device:
        print("Device not found.")
        return

    async with BleakClient(device) as client:
        print("Connected to", device.address)

        def on_rx(_, data):
            print("From Arduino:", data.decode().strip())
            try:
                # TODO: Assign JSON data to x,y,z
                json_data = json.loads(data.decode().strip())
                print("Parsed JSON:", json_data)
                buffer.write(json_data)
            except json.JSONDecodeError:
                print("Failed to decode JSON")

        await client.start_notify(TX_UUID, on_rx)

        while True:
            await asyncio.sleep(1)


def start_ble():
    # start the ble loop
    # equivalent to asyncio.run
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_ble())


# begin ble as a thread
ble_thread = threading.Thread(target=start_ble, daemon=True)
ble_thread.start()

app.layout = html.Div([
    dcc.Graph(id="live-3d-graph"),
    dcc.Interval(
        id="interval-component",
        interval=1 * 1000,
        n_intervals=0  # in milliseconds
    ),
    html.Button("Start/Stop", id="submit-val", n_clicks=0),
])


@app.callback(Output("live-3d-graph", "figure"),
              Input("interval-component", "n_intervals"))
def update_graph(n):
    global x, y, z
    # Generate random data for the 3D scatter plot
    x.append(random.randint(-30, 30))
    y.append(random.randint(-30, 30))
    z.append(random.randint(-30, 30))

    fig = go.Figure(data=[go.Scatter3d(
        x=x,
        y=y,
        z=z,
        mode="lines",
    )])
    fig.update_layout(
        title=dict(text="3D live graph"),
        autosize=False,
        width=1000,
        height=1000,
    )
    return fig


# https://stackoverflow.com/questions/63123501/plotly-dash-dcc-interval-disabled-boolean-documentation
@app.callback(
    Output("interval-component", "disabled"),
    [Input("submit-val", "n_clicks")],
    [State("interval-component", "disabled")],
)
def callback_func_start_stop_interval(button_clicks, disabled_state):
    if button_clicks is not None and button_clicks > 0:
        return not disabled_state
    else:
        return disabled_state


if __name__ == "__main__":
    app.run(debug=True)
