'use strict'

const { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage, shell } = require('electron')
const os = require('os')
const fs = require('fs')
const { spawn } = require('child_process')
const path = require('path')

const isDev = process.argv.includes('--dev')

let mainWindow = null
let tray = null
let serverProcess = null

// ─── Server ───────────────────────────────────────────────────────────────────

function startServer () {
  const serverDir = path.join(__dirname, '..', '..', 'server')

  console.log('[desktop] Starting FastAPI server from:', serverDir)

  serverProcess = spawn('python', ['main.py'], {
    cwd: serverDir,
    stdio: ['ignore', 'pipe', 'pipe'],
    // On Windows, keep the process in its own group so we can kill it cleanly
    detached: false
  })

  serverProcess.stdout.on('data', (data) => {
    process.stdout.write(`[server] ${data}`)
  })

  serverProcess.stderr.on('data', (data) => {
    process.stderr.write(`[server] ${data}`)
  })

  serverProcess.on('close', (code) => {
    console.log(`[desktop] Server process exited with code ${code}`)
    serverProcess = null
  })

  serverProcess.on('error', (err) => {
    console.error('[desktop] Failed to start server:', err.message)
  })
}

function killServer () {
  if (serverProcess) {
    console.log('[desktop] Killing server process…')
    try {
      serverProcess.kill('SIGTERM')
    } catch (e) {
      console.error('[desktop] Error killing server:', e.message)
    }
    serverProcess = null
  }
}

// ─── Window ───────────────────────────────────────────────────────────────────

function createWindow () {
  mainWindow = new BrowserWindow({
    title: 'Local AI Assistant',
    width: 420,
    height: 700,
    minWidth: 380,
    minHeight: 500,
    frame: true,
    backgroundColor: '#0f1117',
    show: false, // revealed on 'ready-to-show'
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  // Hide to tray instead of closing
  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault()
      mainWindow.hide()
    }
  })

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
  })

  return mainWindow
}

function loadURL () {
  if (isDev) {
    console.log('[desktop] Dev mode – loading http://localhost:5173')
    mainWindow.loadURL('http://localhost:5173')
  } else {
    const indexPath = path.join(__dirname, '..', 'frontend', 'dist', 'index.html')
    console.log('[desktop] Production mode – loading', indexPath)
    mainWindow.loadFile(indexPath)
  }
}

// ─── Tray ─────────────────────────────────────────────────────────────────────

function createTray () {
  const iconPath = path.join(__dirname, 'assets', 'icon.png')
  const icon = nativeImage.createFromPath(iconPath)
  tray = new Tray(icon)
  tray.setToolTip('Local AI Assistant')

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show',
      click () {
        if (mainWindow) {
          mainWindow.show()
          mainWindow.focus()
        }
      }
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click () {
        app.isQuitting = true
        app.quit()
      }
    }
  ])

  tray.setContextMenu(contextMenu)

  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

// ─── IPC ──────────────────────────────────────────────────────────────────────

function registerIPC () {
  ipcMain.on('window-minimize', () => {
    if (mainWindow) mainWindow.minimize()
  })

  ipcMain.on('window-maximize', () => {
    if (!mainWindow) return
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize()
    } else {
      mainWindow.maximize()
    }
  })

  ipcMain.on('window-close', () => {
    // Honour tray-hide behaviour
    if (mainWindow) mainWindow.hide()
  })

  ipcMain.on('open-image', (_event, dataUrl) => {
    try {
      const base64 = dataUrl.replace(/^data:image\/\w+;base64,/, '')
      const tmpPath = path.join(os.tmpdir(), `screenshot_${Date.now()}.png`)
      fs.writeFileSync(tmpPath, Buffer.from(base64, 'base64'))
      shell.openPath(tmpPath)
    } catch (e) {
      console.error('[desktop] open-image error:', e.message)
    }
  })
}

// ─── App lifecycle ────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  startServer()
  createWindow()
  createTray()
  registerIPC()

  // Give the FastAPI server 2 seconds to bind before we load the page
  setTimeout(() => {
    loadURL()
  }, 2000)

  app.on('activate', () => {
    // macOS: re-show when clicking dock icon
    if (mainWindow) {
      mainWindow.show()
    }
  })
})

app.on('before-quit', () => {
  app.isQuitting = true
  killServer()
})

// On macOS it is common to keep the app running even when all windows are closed
// On Windows/Linux we want the same "minimize to tray" behaviour, so we prevent
// the default quit that would happen if no windows are open.
app.on('window-all-closed', (event) => {
  // Do nothing – we manage quit via tray / before-quit
})
