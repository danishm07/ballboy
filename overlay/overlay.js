const API = 'http://localhost:5001'

let currentDetections = { players: [], ball: null, total: 0 }
let calibration = null

async function fetchCalibration() {
  try {
    const res = await fetch(`${API}/calibration`)
    if (res.ok) {
      const data = await res.json()
      if (data && data.x1 != null) {
        calibration = data
      }
    }
  } catch (e) {
    console.error('Failed to fetch calibration:', e)
  }
}

function drawDetections(detections) {
  const overlay = document.getElementById('overlay')
  if (!overlay) return
  overlay.innerHTML = ''

  const captureW = detections.width || 1
  const captureH = detections.height || 1

  // Overlay window is sized/positioned to match calibration rect in main.js
  const scaleX = window.innerWidth / captureW
  const scaleY = window.innerHeight / captureH

  ;(detections.players || []).forEach((p) => {
    if ((p.confidence ?? 1) < 0.3) return
    if (p.x1 === undefined || p.x2 === undefined) return

    const left = p.x1 * scaleX
    const top = p.y1 * scaleY
    const width = (p.x2 - p.x1) * scaleX
    const height = (p.y2 - p.y1) * scaleY

    const centerX = (p.x1 + p.x2) / 2
    const isHome = centerX < captureW * 0.5

    const box = document.createElement('div')
    box.style.cssText = `
      position: absolute;
      left: ${left}px;
      top: ${top}px;
      width: ${width}px;
      height: ${height}px;
      border: 2px solid ${isHome ? '#dc3232' : '#4a9eff'};
      box-sizing: border-box;
      pointer-events: none;
    `
    overlay.appendChild(box)
  })

  const ball = detections.ball
  if (ball && ball.x1 !== undefined) {
    const box = document.createElement('div')
    box.style.cssText = `
      position: absolute;
      left: ${ball.x1 * scaleX}px;
      top: ${ball.y1 * scaleY}px;
      width: ${(ball.x2 - ball.x1) * scaleX}px;
      height: ${(ball.y2 - ball.y1) * scaleY}px;
      border: 2px solid #00e6e6;
      box-sizing: border-box;
      pointer-events: none;
    `
    overlay.appendChild(box)
  }
}

async function fetchDetections() {
  try {
    const res = await fetch(`${API}/detections`)
    if (res.ok) {
      currentDetections = await res.json()
      drawDetections(currentDetections)
    }
  } catch (e) {
    console.error('Failed to fetch detections:', e)
  }
}

function startPolling() {
  fetchCalibration().then(() => {
    fetchDetections()
    setInterval(fetchDetections, 200)
    setInterval(fetchCalibration, 5000)
  })
}

window.addEventListener('resize', () => drawDetections(currentDetections))
document.addEventListener('DOMContentLoaded', startPolling)
