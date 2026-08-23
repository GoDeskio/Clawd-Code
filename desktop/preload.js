const { contextBridge, ipcRenderer } = require("electron");

// User-initiated desktop helpers only. Nothing polls the clipboard,
// captures keystrokes, or records the screen in the background.
contextBridge.exposeInMainWorld("clawdDesktop", {
  pickFolder: () => ipcRenderer.invoke("clawd:pickFolder"),
  pickFiles: () => ipcRenderer.invoke("clawd:pickFiles"),
  readClipboardText: () => ipcRenderer.invoke("clawd:readClipboardText"),
  captureScreenshot: () => ipcRenderer.invoke("clawd:captureScreenshot"),
  notify: (title, body) => ipcRenderer.invoke("clawd:notify", { title, body }),
});
