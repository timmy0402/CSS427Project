from flask import Flask, jsonify, render_template_string
import threading
import time
import json
import asyncio
import io
from bleak import BleakScanner, BleakClient
from collections import deque
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Shared data storage
arduino_data_buffer = deque(maxlen=100)  # Keep last 100 readings
latest_arduino_data = {}
connection_status = {"connected": False, "last_update": 0}

# Arduino BLE configuration - EXACT UUIDs from your Arduino code
SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9B"  # Matches your Arduino
RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9B"      # Matches your Arduino  
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9B"      # Matches your Arduino

class ArduinoListener:
    def __init__(self):
        self.running = False
        
    async def connect_and_listen(self):
        """Connect to Arduino and listen for data"""
        while True:
            try:
                logger.info("Scanning for UNO_R4_UART...")
                
                # Scan for devices with longer timeout
                devices = await BleakScanner.discover(timeout=10.0)
                target_device = None
                
                for device in devices:
                    if device.name and "UNO_R4_UART" in device.name:
                        target_device = device
                        logger.info(f"Found Arduino: {device.name} at {device.address}")
                        break
                
                if not target_device:
                    logger.warning("Arduino device not found. Retrying in 5 seconds...")
                    await asyncio.sleep(3)
                    continue

                logger.info(f"Attempting connection to {target_device.address}...")
                
                # Create client with longer timeout
                async with BleakClient(target_device, timeout=20.0) as client:
                    logger.info(f"Connected to Arduino at {target_device.address}")
                    
                    # Wait a moment for services to be discovered
                    await asyncio.sleep(2)
                    
                    # Check if client is still connected
                    if not client.is_connected:
                        logger.error("Connection lost immediately after connecting")
                        continue
                    
                    # List all services and characteristics for debugging
                    logger.info("=== Available services ===")
                    service_found = False
                    tx_char = None
                    
                    for service in client.services:
                        logger.info(f"Service: {service.uuid}")
                        if str(service.uuid).upper() == SERVICE_UUID.upper():
                            service_found = True
                            logger.info(f"  ✓ Found target service!")
                            
                        for char in service.characteristics:
                            logger.info(f"  Characteristic: {char.uuid} - Properties: {char.properties}")
                            if str(char.uuid).upper() == TX_UUID.upper():
                                tx_char = char
                                logger.info(f"    ✓ Found TX characteristic!")
                    
                    if not service_found:
                        logger.error(f"Service {SERVICE_UUID} not found!")
                        logger.info("Available services:")
                        for service in client.services:
                            logger.info(f"  - {service.uuid}")
                        await asyncio.sleep(5)
                        continue
                    
                    if not tx_char:
                        logger.error(f"TX Characteristic {TX_UUID} not found!")
                        await asyncio.sleep(5)
                        continue
                    
                    if "notify" not in tx_char.properties:
                        logger.error("TX characteristic doesn't support notifications!")
                        logger.info(f"Available properties: {tx_char.properties}")
                        await asyncio.sleep(5)
                        continue
                    
                    connection_status["connected"] = True
                    
                    def on_rx(_, data):
                        try:
                            json_str = data.decode().strip()
                            logger.info(f"Received: {json_str}")
                            
                            json_data = json.loads(json_str)
                            
                            # Add timestamp if not present
                            if 'time' not in json_data:
                                json_data['time'] = int(time.time() * 1000)
                            
                            # Update shared data
                            global latest_arduino_data
                            latest_arduino_data = json_data
                            arduino_data_buffer.append(json_data)
                            connection_status["last_update"] = time.time()
                            
                            logger.debug(f"Updated data: {json_data}")
                            
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to decode JSON: {e}")
                        except Exception as e:
                            logger.error(f"Error processing data: {e}")

                    # Start notifications on the TX characteristic
                    try:
                        await client.start_notify(tx_char, on_rx)
                        logger.info("✓ Started listening for Arduino data...")
                    except Exception as e:
                        logger.error(f"Failed to start notifications: {e}")
                        continue
                    
                    # Keep connection alive and monitor
                    heartbeat_count = 0
                    while client.is_connected:
                        await asyncio.sleep(1)
                        heartbeat_count += 1
                        
                        # Log heartbeat every 30 seconds
                        if heartbeat_count % 30 == 0:
                            logger.info(f"Connection active - heartbeat #{heartbeat_count}")
                            
                        # Check if we're still receiving data
                        if (heartbeat_count > 30 and 
                            time.time() - connection_status.get("last_update", 0) > 30):
                            logger.warning("No data received for 30 seconds, checking connection...")
                        
            except asyncio.TimeoutError:
                logger.error("Connection timeout - Arduino might be busy or out of range")
                connection_status["connected"] = False
                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"Connection error: {e}")
                connection_status["connected"] = False
                await asyncio.sleep(5)

def run_arduino_listener():
    """Run the Arduino listener in an async loop"""
    def start_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        listener = ArduinoListener()
        loop.run_until_complete(listener.connect_and_listen())
    
    thread = threading.Thread(target=start_loop, daemon=True)
    thread.start()
    logger.info("Arduino listener started in background thread")

# Web routes
@app.route('/')
def index():
    """Serve the game HTML"""
    return render_template_string(GAME_HTML)

@app.route('/arduino-data')
def get_arduino_data():
    """API endpoint to get latest Arduino data"""
    if latest_arduino_data:
        return jsonify({
            **latest_arduino_data,
            "connection_status": connection_status
        })
    else:
        return jsonify({
            "error": "No data available",
            "connection_status": connection_status
        })

@app.route('/arduino-history')
def get_arduino_history():
    """Get historical Arduino data"""
    return jsonify({
        "data": list(arduino_data_buffer),
        "connection_status": connection_status
    })

@app.route('/status')
def get_status():
    """Get connection status"""
    return jsonify(connection_status)

# HTML template for the game
GAME_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arduino Block Game</title>
    <style>
        body {
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-family: Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        
        .game-container {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .game-info {
            text-align: center;
            margin-bottom: 20px;
            color: white;
        }
        
        .score {
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 10px;
        }
        
        .status {
            font-size: 14px;
            opacity: 0.9;
            margin-bottom: 5px;
        }
        
        .connection-status {
            font-size: 12px;
            opacity: 0.7;
        }
        
        #gameGrid {
            display: grid;
            grid-template-columns: repeat(10, 40px);
            grid-template-rows: repeat(12, 40px);
            gap: 2px;
            background: rgba(0, 0, 0, 0.3);
            padding: 10px;
            border-radius: 10px;
            margin: 0 auto;
        }
        
        .block {
            width: 40px;
            height: 40px;
            border-radius: 6px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            transition: all 0.2s ease;
            position: relative;
        }
        
        .block.player {
            border: 3px solid #fff;
            box-shadow: 0 0 15px rgba(255, 255, 255, 0.6);
            animation: pulse 1s infinite alternate;
        }
        
        .block.breaking {
            animation: break 0.3s ease-out forwards;
        }
        
        @keyframes pulse {
            from { box-shadow: 0 0 15px rgba(255, 255, 255, 0.6); }
            to { box-shadow: 0 0 25px rgba(255, 255, 255, 0.9); }
        }
        
        @keyframes break {
            0% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.2); opacity: 0.7; }
            100% { transform: scale(0); opacity: 0; }
        }
        
        .controls {
            text-align: center;
            margin-top: 20px;
            color: white;
            font-size: 14px;
        }
        
        .color-indicator {
            display: inline-block;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            margin: 0 5px;
            vertical-align: middle;
        }
        
        .connected { color: #4ecdc4; }
        .disconnected { color: #ff6b6b; }
    </style>
</head>
<body>
    <div class="game-container">
        <div class="game-info">
            <div class="score">Score: <span id="score">0</span></div>
            <div class="status">
                Player Color: <span class="color-indicator" id="playerColorIndicator"></span>
            </div>
            <div class="connection-status" id="connectionStatus">Connecting to Arduino...</div>
        </div>
        
        <div id="gameGrid"></div>
        
        <div class="controls">
            <p>Tilt device: Z-axis changes color • X-axis moves left/right • Y-axis moves up/down</p>
            <p>Match your color with blocks to break them! • WASD/Arrow Keys as backup</p>
        </div>
    </div>

    <script>
        class BlockGame {
            constructor() {
                this.gridWidth = 10;
                this.gridHeight = 12;
                this.grid = [];
                this.player = { x: 4, y: 10 };
                this.score = 0;
                this.colors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#feca57', '#ff9ff3', '#a8e6cf'];
                this.playerColor = this.colors[0];
                this.lastMove = 0;
                this.lastTiltMove = 0;
                
                this.initGrid();
                this.render();
                this.setupControls();
                this.startArduinoListener();
                this.gameLoop();
            }
            
            initGrid() {
                this.grid = [];
                for (let y = 0; y < this.gridHeight; y++) {
                    this.grid[y] = [];
                    for (let x = 0; x < this.gridWidth; x++) {
                        if (y < 8) {
                            this.grid[y][x] = {
                                color: this.colors[Math.floor(Math.random() * this.colors.length)],
                                type: 'block'
                            };
                        } else {
                            this.grid[y][x] = null;
                        }
                    }
                }
            }
            
            startArduinoListener() {
                this.checkForArduinoData();
                setInterval(() => {
                    this.checkForArduinoData();
                }, 50); // Check frequently for smooth response
            }
            
            async checkForArduinoData() {
                try {
                    const response = await fetch('/arduino-data');
                    if (response.ok) {
                        const data = await response.json();
                        this.processArduinoData(data);
                    }
                } catch (error) {
                    console.error('Error fetching Arduino data:', error);
                }
            }
            
            processArduinoData(data) {
                if (data.accel && data.connection_status) {
                    const { accel } = data;
                    
                    // Update connection status
                    const statusEl = document.getElementById('connectionStatus');
                    if (data.connection_status.connected) {
                        statusEl.className = 'connection-status connected';
                        statusEl.textContent = `Arduino Connected • X:${accel.x.toFixed(1)} Y:${accel.y.toFixed(1)} Z:${accel.z.toFixed(1)}`;
                    } else {
                        statusEl.className = 'connection-status disconnected';
                        statusEl.textContent = 'Arduino Disconnected';
                        return;
                    }
                    
                    // Color control with Y-axis (normalized from -10 to +10 m/s²)
                    const normalizedY = Math.max(0, Math.min(100, ((accel.y + 10) / 20) * 100));
                    const colorIndex = Math.floor((normalizedY / 100) * this.colors.length);
                    this.playerColor = this.colors[Math.max(0, Math.min(colorIndex, this.colors.length - 1))];
                    document.getElementById('playerColorIndicator').style.backgroundColor = this.playerColor;
                    
                    // Movement control with tilt detection
                    const now = Date.now();
                    if (now - this.lastTiltMove > 300) { // 300ms cooldown for tilt movements
                        const tiltThreshold = 2.5;
                        const zCenter = 9.8;
                        const zDiff = accel.z - zCenter;
                        
                        let moved = false;
                        
                        // X-axis tilt for left/right
                        if (accel.x > tiltThreshold && this.canMove('right')) {
                            this.movePlayer('right');
                            moved = true;
                        } else if (accel.x < -tiltThreshold && this.canMove('left')) {
                            this.movePlayer('left');
                            moved = true;
                        }
                        
                        // Z-axis tilt for up/down
                        if (zDiff > 2 && this.canMove('up')) {
                            this.movePlayer('up');
                            moved = true;
                        } else if (zDiff < -2 && this.canMove('down')) {
                            this.movePlayer('down');
                            moved = true;
                        }
                        
                        if (moved) {
                            this.lastTiltMove = now;
                        }
                    }
                    
                    this.render();
                }
            }
            
            canMove(direction) {
                switch(direction) {
                    case 'up': return this.player.y > 0;
                    case 'down': return this.player.y < this.gridHeight - 1;
                    case 'left': return this.player.x > 0;
                    case 'right': return this.player.x < this.gridWidth - 1;
                    default: return false;
                }
            }
            
            movePlayer(direction) {
                switch(direction) {
                    case 'up': this.player.y--; break;
                    case 'down': this.player.y++; break;
                    case 'left': this.player.x--; break;
                    case 'right': this.player.x++; break;
                }
                this.checkCollision();
            }
            
            setupControls() {
                document.addEventListener('keydown', (e) => {
                    let moved = false;
                    
                    switch(e.key.toLowerCase()) {
                        case 'w':
                        case 'arrowup':
                            if (this.canMove('up')) {
                                this.movePlayer('up');
                                moved = true;
                            }
                            break;
                        case 's':
                        case 'arrowdown':
                            if (this.canMove('down')) {
                                this.movePlayer('down');
                                moved = true;
                            }
                            break;
                        case 'a':
                        case 'arrowleft':
                            if (this.canMove('left')) {
                                this.movePlayer('left');
                                moved = true;
                            }
                            break;
                        case 'd':
                        case 'arrowright':
                            if (this.canMove('right')) {
                                this.movePlayer('right');
                                moved = true;
                            }
                            break;
                    }
                    
                    if (moved) {
                        this.render();
                    }
                });
            }
            
            checkCollision() {
                const currentBlock = this.grid[this.player.y][this.player.x];
                if (currentBlock && currentBlock.color === this.playerColor) {
                    this.breakBlock(this.player.x, this.player.y);
                    this.score += 10;
                    document.getElementById('score').textContent = this.score;
                }
            }
            
            breakBlock(x, y) {
                if (this.grid[y] && this.grid[y][x]) {
                    const element = document.querySelector(`[data-x="${x}"][data-y="${y}"]`);
                    if (element) {
                        element.classList.add('breaking');
                        setTimeout(() => {
                            this.grid[y][x] = null;
                            this.render();
                            this.dropBlocks();
                        }, 300);
                    }
                }
            }
            
            dropBlocks() {
                for (let x = 0; x < this.gridWidth; x++) {
                    let writeIndex = this.gridHeight - 1;
                    for (let y = this.gridHeight - 1; y >= 0; y--) {
                        if (this.grid[y][x] && this.grid[y][x].type === 'block') {
                            if (writeIndex !== y) {
                                this.grid[writeIndex][x] = this.grid[y][x];
                                this.grid[y][x] = null;
                            }
                            writeIndex--;
                        }
                    }
                }
                this.render();
            }
            
            render() {
                const gameGrid = document.getElementById('gameGrid');
                gameGrid.innerHTML = '';
                
                for (let y = 0; y < this.gridHeight; y++) {
                    for (let x = 0; x < this.gridWidth; x++) {
                        const blockElement = document.createElement('div');
                        blockElement.className = 'block';
                        blockElement.setAttribute('data-x', x);
                        blockElement.setAttribute('data-y', y);
                        
                        if (x === this.player.x && y === this.player.y) {
                            blockElement.classList.add('player');
                            blockElement.style.backgroundColor = this.playerColor;
                        } else if (this.grid[y][x]) {
                            blockElement.style.backgroundColor = this.grid[y][x].color;
                        } else {
                            blockElement.style.backgroundColor = 'rgba(255, 255, 255, 0.1)';
                        }
                        
                        gameGrid.appendChild(blockElement);
                    }
                }
            }
            
            gameLoop() {
                if (Math.random() < 0.01) {
                    this.addNewRow();
                }
                
                setTimeout(() => this.gameLoop(), 200);
            }
            
            addNewRow() {
                for (let y = this.gridHeight - 1; y > 0; y--) {
                    for (let x = 0; x < this.gridWidth; x++) {
                        this.grid[y][x] = this.grid[y-1][x];
                    }
                }
                
                for (let x = 0; x < this.gridWidth; x++) {
                    if (Math.random() < 0.6) {
                        this.grid[0][x] = {
                            color: this.colors[Math.floor(Math.random() * this.colors.length)],
                            type: 'block'
                        };
                    } else {
                        this.grid[0][x] = null;
                    }
                }
                
                if (this.player.y < this.gridHeight - 1) {
                    this.player.y++;
                }
                
                this.render();
            }
        }
        
        // Start the game
        const game = new BlockGame();
        document.getElementById('playerColorIndicator').style.backgroundColor = game.playerColor;
    </script>
</body>
</html>'''

def main():
    """Main function to start the web server and Arduino listener"""
    print("Starting Arduino Block Game Server...")
    print("=" * 50)
    
    # Start Arduino listener in background
    run_arduino_listener()
    
    print("🎮 Game server starting on http://localhost:5000")
    print("📱 Arduino listener running in background")
    print("🔗 Make sure your Arduino is running and broadcasting 'UNO_R4_UART'")
    print("=" * 50)
    
    try:
        app.run(host='localhost', port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
    except Exception as e:
        print(f"❌ Server error: {e}")

if __name__ == '__main__':
    main()