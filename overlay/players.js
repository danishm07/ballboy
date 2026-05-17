const { ipcRenderer } = require('electron')

const DEFAULT_POSITIONS = ['GK', 'RB', 'CB', 'CB', 'LB', 'CM', 'CM', 'CM', 'RW', 'ST', 'LW']

let collapsed = false

let currentState = {}
let expandedStatsId = null
let lastLineupKey = ''
window.currentMinute = 0
window.playerLineups = { home: [], away: [] }

let lineupRendered = false

const FALLBACK_LINEUPS = {
  portugal: [
    { name: 'Costa', position: 'GK', number: 22 },
    { name: 'Cancelo', position: 'RB', number: 20 },
    { name: 'Dias', position: 'CB', number: 4 },
    { name: 'Pepe', position: 'CB', number: 3 },
    { name: 'Guerreiro', position: 'LB', number: 5 },
    { name: 'Neves', position: 'CM', number: 18 },
    { name: 'Vitinha', position: 'CM', number: 23 },
    { name: 'B. Fernandes', position: 'CM', number: 8 },
    { name: 'Bernardo', position: 'RW', number: 10 },
    { name: 'Ronaldo', position: 'ST', number: 7 },
    { name: 'Leao', position: 'LW', number: 17 }
  ],
  spain: [
    { name: 'Simon', position: 'GK', number: 23 },
    { name: 'Carvajal', position: 'RB', number: 2 },
    { name: 'Laporte', position: 'CB', number: 24 },
    { name: 'Le Normand', position: 'CB', number: 3 },
    { name: 'Cucurella', position: 'LB', number: 22 },
    { name: 'Rodri', position: 'CM', number: 16 },
    { name: 'Ruiz', position: 'CM', number: 8 },
    { name: 'Olmo', position: 'CM', number: 10 },
    { name: 'Yamal', position: 'RW', number: 19 },
    { name: 'Morata', position: 'ST', number: 7 },
    { name: 'Williams', position: 'LW', number: 17 }
  ]
}

function resolveLineup(state) {
  const lineup = state?.lineup || {}
  let home = (lineup.home || []).slice()
  let away = (lineup.away || []).slice()
  const hasHome = home.some((p) => p?.name)
  const hasAway = away.some((p) => p?.name)
  if (!hasHome || !hasAway) {
    const match = state?.match || {}
    const key = `${(match.team_home || '').toLowerCase()}|${(match.team_away || '').toLowerCase()}`
    const fallbacks = {
      'portugal|spain': { home: 'portugal', away: 'spain' },
      'spain|portugal': { home: 'spain', away: 'portugal' },
      'arsenal fc|manchester city fc': { home: 'arsenal', away: 'manchester city' },
      'arsenal|manchester city': { home: 'arsenal', away: 'manchester city' }
    }
    const fb = fallbacks[key]
    if (fb) {
      if (!hasHome && FALLBACK_LINEUPS[fb.home]) home = FALLBACK_LINEUPS[fb.home]
      if (!hasAway && FALLBACK_LINEUPS[fb.away]) away = FALLBACK_LINEUPS[fb.away]
    }
  }
  return { home, away }
}


function isPreMatch(minute) {
  return minute == null || minute <= 0
}

const FATIGUE_RATE = {
  GK: 0.3,
  CB: 0.5,
  RB: 0.7,
  LB: 0.7,
  DM: 0.8,
  CM: 0.9,
  ST: 0.85,
  CF: 0.85,
  RW: 1.0,
  LW: 1.0,
  AM: 0.95,
  Goalkeeper: 0.3,
  'Centre-Back': 0.5,
  'Right Back': 0.7,
  'Left Back': 0.7,
  'Defensive Midfield': 0.8,
  'Central Midfield': 0.9,
  'Right Wing': 1.0,
  'Left Wing': 1.0,
  'Centre Forward': 0.85,
  'Right Midfield': 0.85,
  'Left Midfield': 0.85,
  'Attacking Midfield': 0.95
}

function playerSeed(name) {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = (hash << 5) - hash + name.charCodeAt(i)
    hash |= 0
  }
  return ((hash % 10) + 10) % 10
}

function getEnergy(minute, position, playerName) {
  const rate = FATIGUE_RATE[position] || 0.7
  const seed = playerSeed(playerName)
  const variation = (seed - 4) * 0.5
  const base = 100 - (minute / 90) * 60 * rate
  return Math.max(5, Math.round(base + variation))
}

function energyForPlayer(minute, position, playerName) {
  if (isPreMatch(minute)) return 100
  return getEnergy(minute, position, playerName || '')
}

function energyBarColor(energy, preMatch = false) {
  if (preMatch) return '#44aa44'
  if (energy > 60) return '#44aa44'
  if (energy >= 30) return '#ffaa00'
  return '#dc3232'
}

function updateStatsPanel(statsEl, minute, position, playerName) {
  if (!statsEl) return
  const energy = energyForPlayer(minute, position, playerName)
  const energyEl = statsEl.querySelector('.stat-energy')
  const distEl = statsEl.querySelector('.stat-distance')
  const sprintEl = statsEl.querySelector('.stat-sprints')
  const posEl = statsEl.querySelector('.stat-position')
  if (energyEl) energyEl.textContent = `${energy}%`
  if (distEl) distEl.textContent = `${(minute * 0.13).toFixed(1)}km`
  if (sprintEl) sprintEl.textContent = String(Math.round(minute * 0.8))
  if (posEl) posEl.textContent = position || '—'
}

function updatePlayerRow(row, minute) {
  if (!row) return
  const preMatch = isPreMatch(minute)
  const fill = row.querySelector('.energy-bar, .energy-fill')
  if (!fill) return
  const position = row.dataset.position || 'CM'
  const playerName = row.dataset.playerName || ''
  const energy = energyForPlayer(minute, position, playerName)
  fill.style.width = `${energy}%`
  fill.style.background = energyBarColor(energy, preMatch)
  const statsId = row.dataset.statsId
  const statsEl = statsId ? document.getElementById(statsId) : null
  if (statsEl && !statsEl.hidden) {
    updateStatsPanel(statsEl, minute, position, playerName)
  }
}

window.updateEnergyBars = function updateEnergyBars(minute) {
  const rows = Array.from(document.querySelectorAll('.player-row'))
  rows.forEach((row, i) => {
    setTimeout(() => updatePlayerRow(row, minute), i * 150)
  })

  document.querySelectorAll('.player-stats:not([hidden])').forEach((statsEl) => {
    updateStatsPanel(
      statsEl,
      minute,
      statsEl.dataset.position || '—',
      statsEl.dataset.playerName || ''
    )
  })
}

function lineupSlots(lineup) {
  const players = (lineup || [])
    .slice()
    .sort((a, b) => (a.formation_index ?? 99) - (b.formation_index ?? 99))
    .slice(0, 11)
  return DEFAULT_POSITIONS.map((pos, i) => {
    const p = players[i]
    if (p) {
      return {
        position: p.position || pos,
        name: p.name || null,
        number: p.number ?? null
      }
    }
    return { position: pos, name: null, number: null }
  })
}

function lineupKey(state) {
  const resolved = resolveLineup(state)
  const home = resolved.home.map((p) => `${p.name}|${p.number}`).join(',')
  const away = resolved.away.map((p) => `${p.name}|${p.number}`).join(',')
  return `${state?.match?.team_home}|${state?.match?.team_away}|${home}|${away}`
}

function playerDisplayName(slot) {
  if (slot.name) {
    const num = slot.number != null ? ` #${slot.number}` : ''
    return `${slot.name}${num}`
  }
  return '—'
}

function toggleStats(team, index, player, minute) {
  const statsId = `stats-${team}-${index}`
  const statsEl = document.getElementById(statsId)
  if (!statsEl) return

  updateStatsPanel(statsEl, minute, player.position, player.name || '')

  document.querySelectorAll('.player-stats').forEach((el) => {
    if (el.id !== statsId) el.hidden = true
  })

  const willShow = statsEl.hidden
  statsEl.hidden = !willShow
  expandedStatsId = willShow ? statsId : null
}

function renderTeam(team, players, minute) {
  const container = document.getElementById(team === 'home' ? 'homeList' : 'awayList')
  if (!container) return

  container.innerHTML = ''
  const list = (players || [])
    .slice()
    .sort((a, b) => (a.formation_index ?? 99) - (b.formation_index ?? 99))
    .slice(0, 11)

  list.forEach((p, i) => {
    if (!p?.name) return
    const energy = energyForPlayer(minute, p.position, p.name)
    const color = energyBarColor(energy, isPreMatch(minute))
    const statsId = `stats-${team}-${i}`

    const wrap = document.createElement('div')
    wrap.className = 'player-row-wrap'

    const row = document.createElement('div')
    row.className = 'player-row'
    row.dataset.index = String(i)
    row.dataset.team = team
    row.dataset.position = p.position || 'CM'
    row.dataset.playerName = p.name
    row.dataset.statsId = statsId
    row.innerHTML = `
      <span class="pos">${p.position || '—'}</span>
      <span class="name">${p.name} #${p.number ?? '—'}</span>
      <div class="energy-wrap">
        <div class="energy-bar" style="width:${energy}%;background:${color}"></div>
      </div>
    `
    row.onclick = () => toggleStats(team, i, p, minute)

    const stats = document.createElement('div')
    stats.className = 'player-stats'
    stats.id = statsId
    stats.dataset.position = p.position || 'CM'
    stats.dataset.playerName = p.name
    stats.hidden = true
    stats.innerHTML = `
      <div>Energy: <span class="stat-energy">${energy}%</span></div>
      <div>Distance: <span class="stat-distance">${(minute * 0.13).toFixed(1)}km</span></div>
      <div>Sprints: <span class="stat-sprints">${Math.round(minute * 0.8)}</span></div>
      <div>Position: <span class="stat-position">${p.position || '—'}</span></div>
    `

    wrap.appendChild(row)
    wrap.appendChild(stats)
    container.appendChild(wrap)
  })
}

function renderLineupLists(state) {
  const minute = state?.match?.minute ?? 0
  window.currentMinute = minute

  const resolved = resolveLineup(state)
  window.playerLineups = { home: resolved.home, away: resolved.away }

  renderTeam('home', resolved.home, minute)
  renderTeam('away', resolved.away, minute)

  if (expandedStatsId) {
    const statsEl = document.getElementById(expandedStatsId)
    if (statsEl) {
      statsEl.hidden = false
      updateStatsPanel(
        statsEl,
        minute,
        statsEl.dataset.position || '—',
        statsEl.dataset.playerName || ''
      )
    }
  }
}


function updateHeader(state) {
  const match = state?.match || {}
  const title = document.getElementById('headerTitle')
  const meta = document.getElementById('headerMeta')
  const homeLabel = document.getElementById('homeLabel')
  const awayLabel = document.getElementById('awayLabel')
  const minute = match.minute ?? 0

  if (title) {
    const home = teamShort(match.team_home || 'HOME').toUpperCase()
    const away = teamShort(match.team_away || 'AWAY').toUpperCase()
    title.textContent = `${home} vs ${away}`
  }
  if (meta) meta.textContent = minute > 0 ? `${minute}′` : 'PRE-MATCH'
  if (homeLabel) homeLabel.textContent = match.team_home || 'HOME'
  if (awayLabel) awayLabel.textContent = match.team_away || 'AWAY'

  const badge = document.getElementById('prematchBadge')
  const note = document.getElementById('prematchNote')
  const pre = isPreMatch(minute)
  if (badge) badge.hidden = !pre
  if (note) note.hidden = !pre
}

function updateAll(state) {
  if (!state) return
  currentState = state
  if (!state.match) state.match = {}
  const minute = state.match.minute ?? 0
  window.currentMinute = minute

  updateHeader(state)

  const key = lineupKey(state)
  if (key !== lastLineupKey || !lineupRendered) {
    lastLineupKey = key
    lineupRendered = true
    renderLineupLists(state)
  }

  updateEnergyBars(minute)
}

async function fetchState() {
  const base = typeof API !== 'undefined' ? API : window.API
  if (!base) {
    console.error('[players] API URL not defined')
    return
  }
  try {
    const res = await fetch(`${base}/unified_state`)
    const state = await res.json()
    updateAll(state)
  } catch (err) {
    console.error('[players] fetch failed:', err)
  }
}

window.renderTeam = renderTeam
window.toggleStats = toggleStats

document.addEventListener('DOMContentLoaded', () => {
  fetchState()
  setInterval(fetchState, 2000)
})
