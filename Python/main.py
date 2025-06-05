import dash
from dash import dcc
from dash import html
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import numpy as np
from bleak import BleakScanner, BleakClient
import asyncio
import threading
import json
import queue
from collections import deque
from scipy.spatial.transform import Rotation as R


SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9C"
RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9C"
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9C"

app = dash.Dash(__name__)

data_queue = queue.Queue()  # Queue for data transfer

axis_limit = 30

curr_rotation = np.eye(3)
curr_time = None

app.layout = html.Div(
    children=[
        dcc.Graph(
            id="live-3d-graph",
            figure=go.Figure(
                data=[
                    go.Scatter3d(
                        x=[0],
                        y=[0],
                        z=[0],
                        mode="lines",
                    )
                ],
                layout=go.Layout(
                    scene=dict(
                        xaxis=dict(range=[-axis_limit, axis_limit]),
                        yaxis=dict(range=[-axis_limit, axis_limit]),
                        zaxis=dict(range=[-axis_limit, axis_limit]),
                    ),
                    title=dict(text="3D live graph"),
                    autosize=False,
                    width=1000,
                    height=1000,
                ),
            ),
        ),
        dcc.Interval(
            id="interval-component", interval=300, n_intervals=0  # in milliseconds
        ),
        html.Button("Start/Stop", id="submit-val", n_clicks=0),
    ]
)


async def run_ble(data_queue: queue.Queue):
    while True:
        print("Scanning for UNO_R4_UART...")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: d.name and "UNO_R4_UART" in d.name
        )
        if not device:
            print("Device not found.")
            await asyncio.sleep(3)
            continue

        # try:
        async with BleakClient(device) as client:
            print("Connected to", device.address)

            def on_rx(_, data):
                try:
                    json_data = json.loads(data.decode().strip())
                    # print(json_data)
                    # time = json_data["time"]
                    new_data = {
                        "a_x": json_data["accel"]["x"],
                        "a_y": json_data["accel"]["y"],
                        "a_z": json_data["accel"]["z"],
                        "g_x": json_data["gyro"]["x"],
                        "g_y": json_data["gyro"]["y"],
                        "g_z": json_data["gyro"]["z"],
                        "time": json_data["time"],
                    }

                    data_queue.put(new_data)
                # data.append(json_data)
                # ("From Arduino:", data.decode().strip())

                except json.JSONDecodeError:
                    print("Failed to decode JSON")

            await client.start_notify(TX_UUID, on_rx)
            while True:
                await asyncio.sleep(1)
        # except Exception as e:
        # print("BLE connection error:", e)
        # await asyncio.sleep(3)


def start_ble(data_queue: queue.Queue):
    # start the ble loop
    # equivalent to asyncio.run
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        print("run ble...")
        loop.run_until_complete(run_ble(data_queue))
    except Exception as e:
        print(f"BLE Thread Exception: {e}")


@app.callback(
    Output("live-3d-graph", "figure"),
    Input("interval-component", "n_intervals"),
    State("live-3d-graph", "figure"),
)
def update_graph(n, current_fig):
    new_data = None
    try:
        new_data = data_queue.get_nowait()
    except queue.Empty:
        print("No data in queue")
        pass
    # calculation
    if new_data:

        # get current graph data
        curr_data = current_fig["data"][0]
        x = list(curr_data["x"])
        y = list(curr_data["y"])
        z = list(curr_data["z"])
        pos = np.array([x[-1], y[-1], z[-1]])

        global curr_time, curr_rotation
        curr_vel = np.array([0, 0, 0])
        if curr_time == None:
            curr_time = new_data["time"]

        dt = (new_data["time"] - curr_time) / 1000

        curr_time = new_data["time"]

        omega = np.array([new_data["g_x"], new_data["g_y"], new_data["g_z"]])
        accel = np.array([new_data["a_x"], new_data["a_y"], new_data["a_z"] - 9.81])

        d_theta = omega * dt
        d_rotation = R.from_rotvec(d_theta).as_matrix()

        new_rotation = np.matmul(curr_rotation, d_rotation)

        new_accel = np.matmul(new_rotation, accel)

        curr_vel = curr_vel + new_accel * dt
        new_pos = pos + curr_vel * dt

        print(
            f"omega: {omega}, accel: {accel}, dt: {dt}, d_theta: {d_theta}, d_rotation: {d_rotation}"
        )
        print(
            f"new_rotation: {new_rotation}, new_accel: {new_accel}, curr_vel={curr_vel}, pos: {new_pos}"
        )
        x.append(new_pos[0] if new_pos[0] <= axis_limit else axis_limit)
        y.append(new_pos[1] if new_pos[1] <= axis_limit else axis_limit)
        z.append(new_pos[2] if new_pos[2] <= axis_limit else axis_limit)

        fig = go.Figure(
            data=[
                go.Scatter3d(
                    x=x,
                    y=y,
                    z=z,
                    mode="lines",
                )
            ]
        )

        return fig

    else:
        return dash.no_update


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
    # begin ble as a thread
    ble_thread = threading.Thread(target=start_ble, args=(data_queue,), daemon=True)
    ble_thread.start()
    app.run(debug=False)
