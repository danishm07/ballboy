const { app, BrowserWindow, screen, globalShortcut, ipcMain } = require('electron')
const path = require('path')
const fs = require('fs')

let playersWin
let analysisWin
let overlayWin
let playersCollapsed = false

const HEADER_STRIP = 36
const DEFAULT_WIDTH = 400
const DEFAULT_HEIGHT = 640
const MIN_WIDTH = 280
const MIN_HEIGHT = 200

function createPlayersWindow() {
  const display = screen.getPrimaryDisplay()
  const { width: screenW, height: workH } = display.workAreaSize
  const x = screenW - DEFAULT_WIDTH * 2 - 40
  const y = display.workArea.y

  playersWin = new BrowserWindow({
    x,
    y,
    width: DEFAULT_WIDTH,
    height: workH,
    minWidth: DEFAULT_WIDTH,
    maxWidth: DEFAULT_WIDTH,
    minHeight: MIN_HEIGHT,
    frame: false,
    transparent: false,
    backgroundColor: '#ffffff',
    alwaysOnTop: true,
    resizable: true,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  })

  playersWin._expandedHeight = workH

  playersWin.on('will-resize', (event, newBounds) => {
    if (newBounds.width !== DEFAULT_WIDTH) {
      event.preventDefault()
    }
  })

  playersWin.loadFile('players.html')
  playersWin.setVisibleOnAllWorkspaces(true)
  playersWin.setAlwaysOnTop(true, 'floating')
  playersWin.webContents.openDevTools({ mode: 'detach' })

  playersWin.webContents.on('before-input-event', (event, input) => {
    if (input.meta && input.alt && input.key.toLowerCase() === 'i') {
      playersWin.webContents.toggleDevTools()
    }
  })
}

function createAnalysisWindow() {
  const display = screen.getPrimaryDisplay()
  const { width: screenW, height: workH } = display.workAreaSize
  const x = screenW - DEFAULT_WIDTH - 24
  const y = display.workArea.y

  analysisWin = new BrowserWindow({
    x,
    y,
    width: DEFAULT_WIDTH,
    height: workH,
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    frame: false,
    transparent: false,
    backgroundColor: '#ffffff',
    alwaysOnTop: true,
    resizable: true,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  })

  analysisWin._expandedHeight = workH

  analysisWin.loadFile('analysis.html')
  analysisWin.setVisibleOnAllWorkspaces(true)
  analysisWin.setAlwaysOnTop(true, 'floating')
}

function loadCalibration() {
  const calPath = path.join(__dirname, '..', 'ballboy', 'calibration.json')
  try {
    const data = JSON.parse(fs.readFileSync(calPath, 'utf8'))
    if (data.x1 != null && data.x2 != null) {
      data.width = data.width || data.x2 - data.x1
      data.height = data.height || data.y2 - data.y1
      return data
    }
  } catch (_) {}
  return null
}

function createOverlayWindow() {
  const display = screen.getPrimaryDisplay()
  const { width: workW, height: workH } = display.workAreaSize
  const cal = loadCalibration()

  let x = 0
  let y = display.workArea.y
  let width = Math.floor(workW * 0.7)
  let height = workH

  if (cal) {
    x = cal.x1
    y = cal.y1
    width = cal.width
    height = cal.height
  }

  overlayWin = new BrowserWindow({
    x,
    y,
    width,
    height,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  })

  overlayWin.loadFile('overlay.html')
  overlayWin.setVisibleOnAllWorkspaces(true)
  overlayWin.setAlwaysOnTop(true, 'screen-saver')
  overlayWin.setIgnoreMouseEvents(true, { forward: true })
}

ipcMain.on('toggle-players', (_event, expand) => {
  if (!playersWin) return
  if (typeof expand === 'boolean') {
    playersCollapsed = !expand
  } else {
    playersCollapsed = !playersCollapsed
  }
  if (playersCollapsed) {
    playersWin._expandedHeight = playersWin.getBounds().height
    playersWin.setSize(DEFAULT_WIDTH, HEADER_STRIP)
  } else {
    const { height: workH } = screen.getPrimaryDisplay().workAreaSize
    const h = playersWin._expandedHeight || workH
    playersWin.setSize(DEFAULT_WIDTH, h)
  }
})

ipcMain.on('resize-window', (event, payload) => {
  const win = BrowserWindow.fromWebContents(event.sender)
  if (!win) return

  const fixedWidth = win === playersWin ? DEFAULT_WIDTH : win.getSize()[0]

  if (payload.mode === 'collapse') {
    if (!win._expandedHeight) {
      win._expandedHeight = win.getBounds().height
    }
    win.setSize(fixedWidth, HEADER_STRIP)
    return
  }

  if (payload.mode === 'expand') {
    const h = win._expandedHeight || DEFAULT_HEIGHT
    win.setSize(fixedWidth, h)
  }
})

function createWindows() {
  createPlayersWindow()
  createAnalysisWindow()
  // createOverlayWindow() — boxes via soccer_tracker.py, not Electron overlay

  globalShortcut.register('CommandOrControl+Shift+B', () => {
    const visible = analysisWin.isVisible()
    if (visible) {
      playersWin.hide()
      analysisWin.hide()
      if (overlayWin) overlayWin.hide()
    } else {
      playersWin.show()
      analysisWin.show()
      if (overlayWin) overlayWin.show()
    }
  })
}

app.whenReady().then(createWindows)

app.on('window-all-closed', () => {
  globalShortcut.unregisterAll()
  app.quit()
})

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
})
