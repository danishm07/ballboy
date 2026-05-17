const API = 'http://localhost:5001'

let currentState = {}
let currentInsight = {}
let lastInsightKey = null
let expandedPlayerKey = null
let simulateEventSource = null
let thinkingBuffers = []
let activeThinkingIndex = -1
let inferenceTimer = null

const DEFAULT_HOME_COLOR = '#c8102e'
const DEFAULT_AWAY_COLOR = '#ffcc00'

const PLAYER_SEASON_STATS = {
  Raya: { goals: 0, assists: 0 },
  White: { goals: 2, assists: 4 },
  Saliba: { goals: 1, assists: 0 },
  Gabriel: { goals: 2, assists: 1 },
  Zinchenko: { goals: 0, assists: 3 },
  Odegaard: { goals: 8, assists: 10 },
  Partey: { goals: 3, assists: 2 },
  Rice: { goals: 4, assists: 6 },
  Saka: { goals: 14, assists: 8 },
  Havertz: { goals: 9, assists: 4 },
  Martinelli: { goals: 11, assists: 5 },
  Ederson: { goals: 0, assists: 1 },
  Walker: { goals: 0, assists: 3 },
  Dias: { goals: 1, assists: 0 },
  Akanji: { goals: 2, assists: 1 },
  Gvardiol: { goals: 1, assists: 4 },
  Rodri: { goals: 6, assists: 5 },
  'De Bruyne': { goals: 4, assists: 12 },
  Silva: { goals: 5, assists: 7 },
  Mahrez: { goals: 8, assists: 9 },
  Haaland: { goals: 22, assists: 4 },
  Grealish: { goals: 6, assists: 8 }
}

const AGENT_LABELS = [
  { key: 'defensive', label: 'DEF' },
  { key: 'offensive', label: 'ATK' },
  { key: 'physical', label: 'PHY' }
]

function teamShortName(name) {
  if (!name) return '—'
  return name.split(' ')[0].toUpperCase()
}

function possessionHome(state) {
  const vision = state.vision || {}
  const stats = state.stats || {}
  const raw = vision.possession_home ?? stats.possession_home ?? 50
  return Math.max(0, Math.min(100, Number(raw) || 50))
}

function playerEnergy(minute) {
  return Math.max(0, Math.round(100 - (minute / 90) * 60))
}

function setTeamColors(homeColor, awayColor) {
  document.documentElement.style.setProperty('--home-color', homeColor || DEFAULT_HOME_COLOR)
  document.documentElement.style.setProperty('--away-color', awayColor || DEFAULT_AWAY_COLOR)
}

async function fetchAll() {
  try {
    const [stateRes, insightRes] = await Promise.all([
      fetch(`${API}/unified_state`),
      fetch(`${API}/insight`)
    ])
    const state = await stateRes.json()
    const insight = await insightRes.json()
    if (state && state.match) {
      currentState = state
      updateMatch(state)
      updateMomentum(state)
      updateLineups(state)
      updatePredictions(state.prediction || {})
    }
    if (insight && insight.headline) {
      updateInsight(insight)
    }
  } catch (_) {}
}

function updateMatch(state) {
  const match = state.match || {}
  const home = match.team_home || 'Home'
  const away = match.team_away || 'Away'
  const score = match.score || { home: 0, away: 0 }
  const minute = match.minute ?? '—'

  document.getElementById('matchTeams').textContent = `${home} · ${away}`
  document.getElementById('matchScore').textContent = `${score.home}–${score.away}`
  document.getElementById('matchMinute').textContent = `${minute}'`
  document.getElementById('homeHeading').textContent = teamShortName(home)
  document.getElementById('awayHeading').textContent = teamShortName(away)

  const colors = state.team_colors || {}
  setTeamColors(colors.home || DEFAULT_HOME_COLOR, colors.away || DEFAULT_AWAY_COLOR)
}

function updateMomentum(state) {
  const pct = possessionHome(state)
  const marker = document.getElementById('momentumMarker')
  const homeHalf = document.getElementById('momentumHomeHalf')
  const awayHalf = document.getElementById('momentumAwayHalf')

  marker.style.left = `${pct}%`
  homeHalf.classList.toggle('glow', pct > 55)
  awayHalf.classList.toggle('glow', pct < 45)
}

function renderPlayerGrid(container, lineup, team, minute) {
  const players = (lineup || []).slice(0, 11)
  const existing = new Map()

  container.querySelectorAll('.player-card').forEach((card) => {
    existing.set(card.dataset.playerKey, card)
  })

  const nextKeys = new Set()

  players.forEach((player) => {
    const key = `${team}-${player.number}-${player.name}`
    nextKeys.add(key)
    let card = existing.get(key)

    if (!card) {
      card = document.createElement('div')
      card.className = 'player-card'
      card.dataset.playerKey = key
      card.innerHTML = `
        <div class="player-card-top">
          <div class="player-number"></div>
          <div class="player-name"></div>
        </div>
        <div class="player-energy-bar"><div class="player-energy-fill"></div></div>
        <div class="player-card-detail"></div>
      `
      card.addEventListener('click', () => togglePlayerCard(card, key))
      container.appendChild(card)
    }

    const energy = playerEnergy(minute)
    const stats = PLAYER_SEASON_STATS[player.name] || { goals: 0, assists: 0 }

    card.querySelector('.player-number').textContent = player.number ?? '—'
    card.querySelector('.player-name').textContent = player.name || '—'
    card.querySelector('.player-energy-fill').style.width = `${energy}%`

    card.querySelector('.player-card-detail').innerHTML = `
      <div>Position: ${player.position || '—'}</div>
      <div>Energy: ${energy}%</div>
      <div>Season goals: ${stats.goals}</div>
      <div>Assists: ${stats.assists}</div>
    `

    card.classList.toggle('expanded', expandedPlayerKey === key)
    existing.delete(key)
  })

  existing.forEach((card) => card.remove())

}

function togglePlayerCard(card, key) {
  if (expandedPlayerKey === key) {
    expandedPlayerKey = null
    card.classList.remove('expanded')
    return
  }
  document.querySelectorAll('.player-card.expanded').forEach((el) => el.classList.remove('expanded'))
  expandedPlayerKey = key
  card.classList.add('expanded')
}

function updateLineups(state) {
  const lineup = state.lineup || {}
  const minute = state.match?.minute || 0
  renderPlayerGrid(document.getElementById('homeGrid'), lineup.home, 'home', minute)
  renderPlayerGrid(document.getElementById('awayGrid'), lineup.away, 'away', minute)
}

function updatePredictions(prediction) {
  const setBar = (barId, pctId, value, fallback = 0) => {
    const pct = value !== undefined ? value : fallback
    document.getElementById(barId).style.width = `${pct}%`
    document.getElementById(pctId).textContent = `${pct}%`
  }

  setBar('goalBar', 'goalPct', prediction.goal_probability)
  setBar('subBar', 'subPct', prediction.substitution_probability)
  setBar('shotBar', 'shotPct', prediction.shots_on_target_probability)
}

function updateAnalysisTime() {
  const el = document.getElementById('analysisTime')
  const now = new Date()
  el.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function showInferenceChoreography(insight) {
  const hud = document.getElementById('inferenceHud')
  const analyzing = document.getElementById('inferenceAnalyzing')
  const agentsEl = document.getElementById('inferenceAgents')
  const durationEl = document.getElementById('inferenceDuration')

  if (inferenceTimer) clearTimeout(inferenceTimer)

  hud.hidden = false
  hud.classList.add('visible')
  analyzing.style.display = 'block'
  agentsEl.textContent = ''
  durationEl.textContent = ''

  const ms = insight.generated_ms || 1400
  const totalSec = (ms / 1000).toFixed(1)

  AGENT_LABELS.forEach((agent, i) => {
    setTimeout(() => {
      const parts = AGENT_LABELS.slice(0, i + 1).map((a) => {
        const done = insight.analysts?.[a.key] ? '✓' : '…'
        return `${a.label} ${done}`
      })
      agentsEl.textContent = parts.join(' ')
    }, 400 + i * 350)
  })

  inferenceTimer = setTimeout(() => {
    analyzing.style.display = 'none'
    durationEl.textContent = `${totalSec}s`
    inferenceTimer = setTimeout(() => {
      hud.hidden = true
      hud.classList.remove('visible')
    }, 2200)
  }, 400 + AGENT_LABELS.length * 350 + 200)
}

function updateInsight(data) {
  const key = `${data.headline}|${data.generated_ms}|${data.minute}`
  const isNew = lastInsightKey !== null && key !== lastInsightKey
  lastInsightKey = key

  const headlineEl = document.getElementById('insightHeadline')
  const actionEl = document.getElementById('insightAction')

  const applyContent = () => {
    headlineEl.textContent = data.headline || '—'
    const action = (data.action || '').trim()
    actionEl.textContent = action ? action : ''
    headlineEl.classList.remove('fade-out')

    const statePred = currentState.prediction || {}
    if (data.prediction || statePred) {
      updatePredictions({
        goal_probability: data.prediction?.goal_probability ?? statePred.goal_probability,
        substitution_probability: data.prediction?.sub_probability ?? statePred.substitution_probability,
        shots_on_target_probability:
          data.prediction?.shots_on_target_probability ?? statePred.shots_on_target_probability
      })
    }

    const ms = data.generated_ms || 0
    if (ms) {
      document.getElementById('footerMeta').textContent =
        `4 models · ${(ms / 1000).toFixed(1)}s · Wafer`
    }
  }

  if (isNew && data.headline) {
    headlineEl.classList.add('fade-out')
    setTimeout(applyContent, 180)
    showInferenceChoreography(data)
  } else {
    applyContent()
  }

  currentInsight = data
}

function closeSimulateStream() {
  if (simulateEventSource) {
    simulateEventSource.close()
    simulateEventSource = null
  }
}

function setThinkingScenarioActive(index) {
  activeThinkingIndex = index
  document.querySelectorAll('.scenario-row').forEach((row) => {
    row.classList.toggle('active', Number(row.dataset.index) === index)
  })
}

function appendThinkingToken(index, token) {
  if (!token) return
  thinkingBuffers[index] = (thinkingBuffers[index] || '') + token
  if (index === activeThinkingIndex) {
    const stream = document.getElementById('thinkingStream')
    stream.textContent = thinkingBuffers[index]
    stream.scrollTop = stream.scrollHeight
  }
}

function scenarioReasons(scenario) {
  if (scenario.reasons?.length) return scenario.reasons
  if (scenario.predictions?.length) {
    return scenario.predictions.map((p) => {
      if (typeof p === 'string') return p
      const label = p.label || '—'
      const pct = p.pct !== undefined ? ` (${p.pct}%)` : ''
      return `${label}${pct}`
    })
  }
  return ['No reasoning available.']
}

function addScenarioRow(scenario, index, listEl) {
  const li = document.createElement('li')
  li.className = 'scenario-row'
  li.dataset.index = String(index)

  const reasons = scenarioReasons(scenario)
  const reasonsHtml = reasons.map((r) => `<li>${r}</li>`).join('')

  li.innerHTML = `
    <div class="scenario-row-header">
      <span class="scenario-title">${scenario.title || `Scenario ${index + 1}`}</span>
      <span class="scenario-prob">${scenario.probability ?? 0}%</span>
    </div>
    <ul class="scenario-reasons">${reasonsHtml}</ul>
  `

  li.querySelector('.scenario-row-header').addEventListener('click', () => {
    const wasExpanded = li.classList.contains('expanded')
    document.querySelectorAll('.scenario-row.expanded').forEach((row) => row.classList.remove('expanded'))
    if (!wasExpanded) li.classList.add('expanded')
  })

  listEl.appendChild(li)
}

function runSimulate() {
  const btn = document.getElementById('simulateBtn')
  const panel = document.getElementById('simulatePanel')
  const stream = document.getElementById('thinkingStream')
  const listEl = document.getElementById('scenarioList')

  btn.disabled = true
  btn.textContent = 'Simulating…'
  panel.hidden = false
  stream.textContent = ''
  listEl.innerHTML = ''
  thinkingBuffers = []
  activeThinkingIndex = -1

  closeSimulateStream()

  const scenarios = new Array(6).fill(null)
  simulateEventSource = new EventSource(`${API}/simulate/stream`)

  simulateEventSource.addEventListener('scenario_start', (e) => {
    const { index, seed } = JSON.parse(e.data)
    setThinkingScenarioActive(index)
    if (seed && index === activeThinkingIndex) {
      stream.textContent = thinkingBuffers[index] || ''
    }
  })

  simulateEventSource.addEventListener('thinking', (e) => {
    const { index, token } = JSON.parse(e.data)
    if (activeThinkingIndex < 0) setThinkingScenarioActive(index)
    appendThinkingToken(index, token)
  })

  simulateEventSource.addEventListener('scenario_done', (e) => {
    const { index, scenario } = JSON.parse(e.data)
    if (thinkingBuffers[index]) scenario.thinking = thinkingBuffers[index]
    scenarios[index] = scenario
    addScenarioRow(scenario, index, listEl)
  })

  simulateEventSource.addEventListener('complete', (e) => {
    const data = JSON.parse(e.data)
    if (data.generated_ms) {
      document.getElementById('footerMeta').textContent =
        `4 models · ${(data.generated_ms / 1000).toFixed(1)}s · Wafer`
    }
    closeSimulateStream()
    btn.disabled = false
    btn.textContent = '→ Simulate next 10 min'
  })

  simulateEventSource.addEventListener('simulate_error', (e) => {
    try {
      const { error } = JSON.parse(e.data)
      stream.textContent = error || 'Simulation failed.'
    } catch (_) {}
    closeSimulateStream()
    btn.disabled = false
    btn.textContent = '→ Simulate next 10 min'
  })

  simulateEventSource.onerror = () => {
    if (simulateEventSource?.readyState === EventSource.CLOSED) {
      if (!scenarios.some(Boolean)) {
        stream.textContent = 'Connection failed.'
      }
      closeSimulateStream()
      btn.disabled = false
      btn.textContent = '→ Simulate next 10 min'
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  setTeamColors(DEFAULT_HOME_COLOR, DEFAULT_AWAY_COLOR)
  updateAnalysisTime()
  setInterval(updateAnalysisTime, 1000)
  setInterval(fetchAll, 2000)
  fetchAll()

  document.getElementById('simulateBtn').addEventListener('click', runSimulate)
})
