const { ipcRenderer } = require('electron')

const handle = document.getElementById('resizeHandle')
let dragging = false

handle.addEventListener('mousedown', (e) => {
  e.preventDefault()
  dragging = true
  handle.classList.add('dragging')
  ipcRenderer.send('column-resize-start')
})

window.addEventListener('mousemove', (e) => {
  if (!dragging) return
  ipcRenderer.send('column-resize-move', { screenX: e.screenX })
})

window.addEventListener('mouseup', () => {
  if (!dragging) return
  dragging = false
  handle.classList.remove('dragging')
  ipcRenderer.send('column-resize-end')
})
