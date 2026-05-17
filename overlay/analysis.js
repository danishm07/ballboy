const { ipcRenderer } = require('electron')

let collapsed = false
let currentState = {}
let lastInsightKey = null
let lastInsight = null
let currentDetectionFps = null
let headerAnimTimer = null
let simulateEventSource = null
let simulateProgressSource = null
let simulateRunning = false
let thinkingBuffers = []
let activeThinkingIndex = -1
let previousUrgency = null
let insightTimestampMs = null
let insightUpdatedInterval = null
let lastDisplayedMinute = null

const AGENTS = [
  { key: 'defensive', label: 'DEF' },
  { key: 'offensive', label: 'ATK' },
  { key: 'physical', label: 'PHY' }
]

function setupCollapse() {
  const toggle = document.getElementById('windowCollapseToggle')
  if (!toggle) return

  toggle.addEventListener('click', (e) => {
    e.preventDefault()
    e.stopPropagation()
    collapsed = !collapsed
    document.body.classList.toggle('collapsed', collapsed)
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true')
    toggle.textContent = collapsed ? '+' : '−'
    ipcRenderer.send('resize-window', { mode: collapsed ? 'collapse' : 'expand' })
  })
}

function updateMatchContext(state) {
  const el = document.getElementById('matchContext')
  if (!el) return

  const match = state?.match || {}
  const vision = state?.vision || {}
  const minute = match.minute ?? '—'
  const home = teamShort(match.team_home || 'Home').toUpperCase().slice(0, 3)
  const away = teamShort(match.team_away || 'Away').toUpperCase().slice(0, 3)
  const score = match.score || { home: 0, away: 0 }
  const sh = score.home ?? 0
  const sa = score.away ?? 0
  let homeClass = ''
  let awayClass = ''
  if (sh < sa) homeClass = 'score-losing'
  else if (sa < sh) awayClass = 'score-losing'
  const ball = escapeHtml(String(vision.ball_zone || 'unknown').replace(/_/g, '_'))
  const shape = escapeHtml(String(vision.team_shape || 'unknown').replace(/_/g, '_'))

  el.innerHTML =
    `Min <span id="matchMinute" class="match-minute">${minute}</span> · ` +
    `${escapeHtml(home)} <span class="score-home ${homeClass}">${sh}</span>` +
    `-<span class="score-away ${awayClass}">${sa}</span> ${escapeHtml(away)} · ` +
    `Ball: ${ball} · Shape: ${shape}`

  const minuteEl = document.getElementById('matchMinute')
  if (
    minuteEl &&
    lastDisplayedMinute !== null &&
    lastDisplayedMinute !== minute &&
    minute !== '—'
  ) {
    minuteEl.classList.remove('pulse')
    void minuteEl.offsetWidth
    minuteEl.classList.add('pulse')
    setTimeout(() => minuteEl.classList.remove('pulse'), 500)
  }
  lastDisplayedMinute = minute
}

function setInsightTimestamp(insight) {
  if (insight?.timestamp) {
    insightTimestampMs = Math.round(Number(insight.timestamp) * 1000)
  } else {
    insightTimestampMs = Date.now()
  }
}

function updateInsightUpdatedLabel() {
  const el = document.getElementById('insightUpdated')
  if (!el) return
  if (!insightTimestampMs) {
    el.textContent = ''
    return
  }
  const sec = Math.max(0, Math.floor((Date.now() - insightTimestampMs) / 1000))
  el.textContent = `Updated ${sec} second${sec === 1 ? '' : 's'} ago`
}

function setSimulateLoading(loading) {
  const loadingEl = document.getElementById('simulateLoading')
  if (loadingEl) loadingEl.hidden = !loading
}

function resetSimulateButton() {
  setSimulateLoading(false)
  simulateRunning = false
  updateRunPredictButton()
}

function updateRunPredictButton() {
  const btn = document.getElementById('runPredictBtn')
  if (!btn) return
  const listEl = document.getElementById('scenarioTree')
  const hasResults = listEl && listEl.children.length > 0
  btn.disabled = simulateRunning
  btn.textContent = simulateRunning
    ? 'Running…'
    : hasResults
      ? '↻ Predict Next 5 Minutes'
      : '→ Predict Next 5 Minutes'
}

function setTeamColors(state) {
  const colors = state.team_colors || {}
  document.documentElement.style.setProperty('--home-color', colors.home || '#c8102e')
  document.documentElement.style.setProperty('--away-color', colors.away || '#ffcc00')
}

function updateMomentum(state) {
  const poss =
    state?.prediction?.momentum ??
    state?.smoothed_momentum ??
    50

  const homeWidth = poss + '%'
  const awayWidth = 100 - poss + '%'

  const homeSegment = document.getElementById('momentumHomeSegment')
  const awaySegment = document.getElementById('momentumAwaySegment')
  const label = document.getElementById('momentumLabel')

  if (homeSegment) {
    homeSegment.style.flex = 'none'
    homeSegment.style.width = homeWidth
  }
  if (awaySegment) {
    awaySegment.style.flex = 'none'
    awaySegment.style.width = awayWidth
  }

  const homeTeam = teamShort(state?.match?.team_home || 'Home')
  const awayTeam = teamShort(state?.match?.team_away || 'Away')

  if (label) {
    label.textContent = `${homeTeam} ←→ ${awayTeam}`
  }

  const bar = document.getElementById('momentumBar')
  if (bar) {
    if (poss > 60) bar.style.boxShadow = '0 0 8px rgba(220,50,50,0.4)'
    else if (poss < 40) bar.style.boxShadow = '0 0 8px rgba(220,180,50,0.4)'
    else bar.style.boxShadow = 'none'
  }
}

function updateAll(state, insight) {
  if (!state?.match) return

  currentState = state
  console.log(
    'momentum:',
    state?.prediction?.momentum,
    'ball_zone:',
    state?.vision?.ball_zone
  )
  setTeamColors(state)
  updateMomentum(state)
  updateMatchContext(state)
  updateQuantPredictions(state)

  if (insight?.headline) {
    updateInsight(insight)
  }
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function patchQuantBar(containerId, title, breakdown, barClass) {
  const el = document.getElementById(containerId)
  if (!el?.querySelector('.quant-bar-fill')) return false
  const header = el.querySelector('.quant-row-label')
  const fill = el.querySelector('.quant-bar-fill')
  const pct = el.querySelector('.quant-pct')
  if (header) header.textContent = `${title} — ${breakdown.prob}%`
  fill.className = `quant-bar-fill ${barClass}`
  fill.style.width = `${breakdown.prob}%`
  if (pct) pct.textContent = `${breakdown.prob}%`
  return true
}

function renderQuantBlock(containerId, title, breakdown, barClass) {
  const el = document.getElementById(containerId)
  const wasExpanded = el.classList.contains('expanded')
  const stepsHtml = breakdown.steps.map((s) => `<div>${escapeHtml(s)}</div>`).join('')

  el.className = 'quant-row'
  el.innerHTML = `
    <button type="button" class="quant-row-header" aria-expanded="false">
      <span class="quant-row-label">${escapeHtml(title)} — ${breakdown.prob}%</span>
      <span class="quant-row-chevron" aria-hidden="true">+</span>
    </button>
    <div class="quant-row-body">
      <div class="quant-steps">${stepsHtml}</div>
      <div class="quant-bar-row">
        <div class="quant-bar"><div class="quant-bar-fill ${barClass}" style="width:${breakdown.prob}%"></div></div>
        <span class="quant-pct">${breakdown.prob}%</span>
      </div>
    </div>
  `

  const header = el.querySelector('.quant-row-header')
  header.addEventListener('click', () => {
    el.classList.toggle('expanded')
    header.setAttribute('aria-expanded', el.classList.contains('expanded') ? 'true' : 'false')
  })

  if (wasExpanded) {
    el.classList.add('expanded')
    header.setAttribute('aria-expanded', 'true')
  }
}

function pressIntensityDisplay(state) {
  const raw = String(state?.vision?.pressing_intensity || 'medium').toLowerCase()
  if (raw === 'high') return { label: 'HIGH', color: '#dc3232', width: 85 }
  if (raw === 'low') return { label: 'LOW', color: '#44aa44', width: 25 }
  return { label: 'MEDIUM', color: '#ffaa00', width: 55 }
}

function renderPressIntensityBlock(containerId, state) {
  const el = document.getElementById(containerId)
  if (!el) return

  const wasExpanded = el.classList.contains('expanded')
  const press = pressIntensityDisplay(state)
  const stats = state?.stats || {}
  const homePress = stats.press_events_home ?? '—'
  const awayPress = stats.press_events_away ?? '—'

  el.className = 'quant-row'
  el.innerHTML = `
    <button type="button" class="quant-row-header" aria-expanded="false">
      <span class="quant-row-label">Press intensity — <span class="press-level" style="color:${press.color}">${press.label}</span></span>
      <span class="quant-row-chevron" aria-hidden="true">+</span>
    </button>
    <div class="quant-row-body">
      <div class="quant-steps">
        <div>Source: vision.pressing_intensity</div>
        <div>Press events (home/away): ${homePress} / ${awayPress}</div>
      </div>
      <div class="quant-bar-row">
        <div class="quant-bar"><div class="quant-bar-fill press" style="width:${press.width}%;background:${press.color}"></div></div>
        <span class="quant-pct press-pct" style="color:${press.color}">${press.label}</span>
      </div>
    </div>
  `

  const header = el.querySelector('.quant-row-header')
  header.addEventListener('click', () => {
    el.classList.toggle('expanded')
    header.setAttribute('aria-expanded', el.classList.contains('expanded') ? 'true' : 'false')
  })

  if (wasExpanded) {
    el.classList.add('expanded')
    header.setAttribute('aria-expanded', 'true')
  }
}

function updateQuantPredictions(state) {
  const pred = state.prediction || {}
  const goal = computeGoalBreakdown(state)
  const sub = computeSubBreakdown(state)

  if (pred.goal_probability !== undefined) {
    goal.prob = pred.goal_probability
    goal.steps[goal.steps.length - 1] = `Result: ${goal.prob}%`
  }
  if (pred.substitution_probability !== undefined) {
    sub.prob = pred.substitution_probability
    sub.steps[sub.steps.length - 1] = `Result: ${sub.prob}%`
  }

  if (!patchQuantBar('goalQuant', 'Goal probability', goal, 'goal')) {
    renderQuantBlock('goalQuant', 'Goal probability', goal, 'goal')
  }
  if (!patchQuantBar('subQuant', 'Substitution probability', sub, 'sub')) {
    renderQuantBlock('subQuant', 'Substitution probability', sub, 'sub')
  }
  renderPressIntensityBlock('pressQuant', state)
}

function appendAgentLine(tag, text, options = {}) {
  const { dim = false, plain = false } = options
  const panel = document.getElementById('agentPanel')
  const line = document.createElement('div')
  line.className = 'agent-line' + (dim ? ' agent-line-dim' : '')

  if (plain || !tag) {
    line.innerHTML = `<span class="agent-text">${escapeHtml(text)}</span>`
  } else {
    line.innerHTML =
      `<span class="agent-tag">[${escapeHtml(tag)}]</span>` +
      `<span class="agent-text">${escapeHtml(text)}</span>`
  }

  panel.appendChild(line)
  panel.scrollTop = panel.scrollHeight
  return line
}

function clearAgentPanel() {
  document.getElementById('agentPanel').innerHTML = ''
}

async function playAgentPanel(insight) {
  clearAgentPanel()
  const analysts = insight.analysts || {}
  const lines = [
    { tag: 'DEF', text: analysts.defensive?.insight },
    { tag: 'ATK', text: analysts.offensive?.insight },
    { tag: 'PHY', text: analysts.physical?.insight },
    { tag: 'SYNTH', text: `Complete — ${insight.generated_ms || 0}ms`, dim: true }
  ]

  for (const line of lines) {
    await delay(200)
    appendAgentLine(line.tag, line.text || '—', { dim: line.dim })
  }
}

function buildHeaderHtml(insight, options = {}) {
  const { pulse = false } = options
  const parts = []
  const ms = insight?.generated_ms || 0

  if (ms) {
    const sec = parseFloat((ms / 1000).toFixed(1))
    let timerClass = 'timer-fast'
    if (sec > 2.0) timerClass = 'timer-slow'
    else if (sec >= 1.0) timerClass = 'timer-mid'
    const pulseClass = pulse ? ' timer-pulse' : ''
    parts.push(
      `<span class="analysis-timer ${timerClass}${pulseClass}">⚡ ${sec.toFixed(1)}s</span>`
    )
  }

  if (currentDetectionFps != null && currentDetectionFps > 0) {
    parts.push(`<span class="header-fps">${currentDetectionFps.toFixed(1)} fps</span>`)
  }

  return parts.join('<span class="header-sep">·</span>')
}

function updateHeaderTimer(insight, options = {}) {
  const el = document.getElementById('headerAgents')
  if (!el) return

  const html = buildHeaderHtml(insight, options)
  if (!html) {
    el.innerHTML = ''
    return
  }

  el.innerHTML = html

  if (options.pulse) {
    requestAnimationFrame(() => {
      const timer = el.querySelector('.analysis-timer')
      if (timer) {
        timer.addEventListener(
          'animationend',
          () => timer.classList.remove('timer-pulse'),
          { once: true }
        )
      }
    })
  }
}

async function fetchDetectionFps() {
  try {
    const res = await fetch(`${API}/detections`)
    const data = await res.json()
    if (data.fps != null && data.fps > 0) {
      currentDetectionFps = data.fps
      if (!headerAnimTimer) {
        updateHeaderTimer(lastInsight || {})
      }
    }
  } catch (_) {}
}

function animateHeaderAgents(insight) {
  if (headerAnimTimer) {
    clearTimeout(headerAnimTimer)
    headerAnimTimer = null
  }

  const el = document.getElementById('headerAgents')
  if (!el) return

  el.innerHTML = ''
  AGENTS.forEach((agent, i) => {
    setTimeout(() => {
      const parts = AGENTS.slice(0, i + 1).map((a) => `${a.label} ✓`)
      el.innerHTML = `<span class="agent-checks">${parts.join(' ')}</span>`
    }, 300 + i * 400)
  })
  // final timer set by updateHeaderTimer in timeout below

  headerAnimTimer = setTimeout(() => {
    updateHeaderTimer(insight, { pulse: true })
    headerAnimTimer = null
  }, 300 + AGENTS.length * 400 + 150)
}

let activeLogTab = 'analysis'
let dataSourcesInterval = null

function switchLogTab(tab) {
  activeLogTab = tab
  const analysisPanel = document.getElementById('agentPanel')
  const sourcesPanel = document.getElementById('dataSourcesPanel')
  const tabAnalysis = document.getElementById('tabAnalysis')
  const tabSources = document.getElementById('tabSources')
  const label = document.getElementById('agentToggleLabel')

  tabAnalysis?.classList.toggle('active', tab === 'analysis')
  tabSources?.classList.toggle('active', tab === 'sources')

  if (analysisPanel) analysisPanel.hidden = tab !== 'analysis'
  if (sourcesPanel) sourcesPanel.hidden = tab !== 'sources'
  if (label) label.textContent = tab === 'analysis' ? 'Analysis log' : 'Data sources'

  if (tab === 'sources') {
    fetchDataSources()
    if (!dataSourcesInterval) {
      dataSourcesInterval = setInterval(fetchDataSources, 3000)
    }
  } else if (dataSourcesInterval) {
    clearInterval(dataSourcesInterval)
    dataSourcesInterval = null
  }
}

function formatLatency(ms) {
  if (ms == null || ms === '') return '—'
  return `${ms}ms`
}

function sourceBorderColor(name) {
  const n = (name || '').toLowerCase()
  if (n === 'vision') return '#4a9eff'
  if (n === 'predictions') return '#44aa44'
  if (n.includes('analyst') || n === 'synthesizer') return '#dc3232'
  return '#888888'
}

function renderDataSources(data) {
  const list = document.getElementById('dataSourcesList')
  const totalEl = document.getElementById('dataSourcesTotal')
  if (!list) return

  const sources = data?.sources || []
  list.innerHTML = sources
    .map((row, i) => {
      const border = sourceBorderColor(row.name)
      const ms = row.latency_ms
      const timeClass =
        ms != null && ms !== '' && Number(ms) > 1000 ? 'ds-time ds-time-slow' : 'ds-time'
      return `
    <div class="ds-row ${i % 2 ? 'ds-alt' : ''}" style="border-left: 3px solid ${border}">
      <div class="ds-row-top">
        <span class="ds-name">${escapeHtml(row.name)}</span>
        <span class="ds-model">${escapeHtml(row.model || '—')}</span>
        <span class="${timeClass}">${formatLatency(ms)}</span>
      </div>
      <div class="ds-data">${escapeHtml(row.data || '—')}</div>
    </div>`
    })
    .join('')

  const totalSec = ((data?.total_ms || 0) / 1000).toFixed(1)
  if (totalEl) {
    totalEl.textContent =
      `TOTAL: ${totalSec}s | 5 models | 3 parallel Wafer calls`
  }
}

async function fetchDataSources() {
  try {
    const res = await fetch(`${API}/data_sources`)
    const data = await res.json()
    renderDataSources(data)
  } catch (_) {}
}

function setupAgentCollapse() {
  const section = document.getElementById('agentSection')
  const toggle = document.getElementById('agentToggle')
  if (!section || !toggle) return

  document.getElementById('tabAnalysis')?.addEventListener('click', () => switchLogTab('analysis'))
  document.getElementById('tabSources')?.addEventListener('click', () => switchLogTab('sources'))

  toggle.addEventListener('click', () => {
    const collapsed = section.classList.toggle('collapsed')
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true')
    const chevron = toggle.querySelector('.agent-chevron')
    if (chevron) chevron.textContent = collapsed ? '▼' : '▲'
    if (collapsed && dataSourcesInterval) {
      clearInterval(dataSourcesInterval)
      dataSourcesInterval = null
    } else if (!collapsed && activeLogTab === 'sources') {
      fetchDataSources()
      dataSourcesInterval = setInterval(fetchDataSources, 3000)
    }
  })
}

function setupPredictCollapse() {
  const section = document.getElementById('predictSection')
  const toggle = document.getElementById('predictToggle')
  const body = document.getElementById('predictSectionBody')
  const runBtn = document.getElementById('runPredictBtn')
  if (!section || !toggle || !body) return

  toggle.addEventListener('click', () => {
    const isCollapsed = section.classList.toggle('collapsed')
    body.hidden = isCollapsed
    toggle.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true')
    const chevron = toggle.querySelector('.predict-chevron')
    if (chevron) chevron.textContent = isCollapsed ? '▼' : '▲'
  })

  runBtn?.addEventListener('click', (e) => {
    e.preventDefault()
    e.stopPropagation()
    runSimulate()
  })
}

function expandPredictSection() {
  const section = document.getElementById('predictSection')
  const body = document.getElementById('predictSectionBody')
  const toggle = document.getElementById('predictToggle')
  if (!section || !body) return
  section.classList.remove('collapsed')
  body.hidden = false
  if (toggle) {
    toggle.setAttribute('aria-expanded', 'true')
    const chevron = toggle.querySelector('.predict-chevron')
    if (chevron) chevron.textContent = '▲'
  }
}

function updateInsight(insight) {
  const key = `${insight.headline}|${insight.generated_ms}|${insight.minute}`
  const isNew = lastInsightKey !== null && key !== lastInsightKey
  lastInsightKey = key
  lastInsight = insight
  setInsightTimestamp(insight)
  updateInsightUpdatedLabel()

  const headlineEl = document.getElementById('insightHeadline')
  const coachEl = document.getElementById('coachAlert')
  const urgency = String(insight.urgency || 'low').toLowerCase()
  const isHigh = urgency === 'high'
  const showCoachBanner = isHigh && previousUrgency !== 'high'

  const apply = () => {
    headlineEl.textContent = insight.headline || '—'
    headlineEl.classList.remove('fade-out')
    headlineEl.style.color = '#111111'
    if (coachEl) coachEl.hidden = !showCoachBanner

    const ms = insight.generated_ms || 0
    if (ms) {
      document.getElementById('footerMeta').textContent =
        `4 models · ${(ms / 1000).toFixed(1)}s · Wafer`
    }
  }

  previousUrgency = urgency

  if (isNew && insight.headline) {
    headlineEl.classList.add('fade-out')
    setTimeout(apply, 300)
    animateHeaderAgents(insight)
    playAgentPanel(insight)
  } else {
    apply()
    if (insight.generated_ms) {
      updateHeaderTimer(insight)
    }
    if (insight.analysts && !document.getElementById('agentPanel').children.length) {
      playAgentPanel(insight)
    }
  }
}

function buildPredictIntroLines(state) {
  const match = state?.match || {}
  const vision = state?.vision || {}
  const home = teamShort(match.team_home || 'Home').toUpperCase().slice(0, 3)
  const away = teamShort(match.team_away || 'Away').toUpperCase().slice(0, 3)
  const score = match.score || { home: 0, away: 0 }
  const minute = match.minute ?? 0
  const poss = possessionHome(state)
  const shape = (vision.team_shape || 'unknown').replace(/_/g, '_')

  return [
    `→ Match state: min ${minute} | ${home} ${score.home}-${score.away} ${away}`,
    `→ Possession: ${poss}% | Shape: ${shape}`,
    '→ Launching 6 parallel Wafer calls...'
  ]
}

function buildScenarioSeedLabels(state) {
  const match = state?.match || {}
  const home = teamShort(match.team_home || 'Home')
  const away = teamShort(match.team_away || 'Away')
  return [
    `${home} scores`,
    `${away} equalizes`,
    'Double substitution',
    'High press',
    'Low block',
    'No change'
  ]
}

function formatPredictContext(state) {
  const match = state?.match || {}
  const minute = match.minute ?? 0
  const home = teamShort(match.team_home || 'Home').toUpperCase().slice(0, 3)
  const away = teamShort(match.team_away || 'Away').toUpperCase().slice(0, 3)
  const score = match.score || { home: 0, away: 0 }
  return `Predicted at min ${minute} · ${home} ${score.home}-${score.away} ${away}`
}

function setPredictContext(state) {
  const el = document.getElementById('predictContext')
  if (!el) return
  el.textContent = formatPredictContext(state)
  el.hidden = false
}

function clearPredictTerminal() {
  const el = document.getElementById('predictTerminal')
  if (el) {
    el.innerHTML = ''
    el.hidden = true
  }
}

function appendPredictTerminalLine(text) {
  const el = document.getElementById('predictTerminal')
  if (!el) return
  el.hidden = false
  const line = document.createElement('div')
  line.className = 'predict-terminal-line'
  line.textContent = text
  el.appendChild(line)
  el.scrollTop = el.scrollHeight
}

async function playPredictTerminalIntro(state) {
  const el = document.getElementById('predictTerminal')
  if (!el) return
  el.hidden = false
  el.innerHTML = ''

  for (const line of buildPredictIntroLines(state)) {
    await delay(300)
    appendPredictTerminalLine(line)
  }
}

function formatWaferTime(scenario) {
  const ms = scenario.response_ms ?? scenario.wafer_ms ?? 0
  return `${(ms / 1000).toFixed(1)}s`
}

function scenarioReasons(scenario) {
  if (scenario.reasons?.length) return scenario.reasons.slice(0, 3)
  if (scenario.predictions?.length) {
    return scenario.predictions.slice(0, 3).map((p) => {
      if (typeof p === 'string') return p
      return p.pct !== undefined ? `${p.label} (${p.pct}%)` : p.label
    })
  }
  return ['No reasoning available.']
}

function addScenarioRow(scenario, index, listEl, isMostLikely) {
  const li = document.createElement('li')
  li.className = 'scenario-row' + (isMostLikely ? ' most-likely' : '')
  li.dataset.index = String(index)

  const reasons = scenarioReasons(scenario)
  const prob = scenario.probability ?? 0
  const waferTime = formatWaferTime(scenario)
  const title = scenario.title || `Scenario ${index + 1}`

  li.innerHTML = `
    <div class="scenario-row-header">
      <span class="scenario-name">${escapeHtml(title)} | ${waferTime}</span>
      <div class="scenario-bar"><div class="scenario-bar-fill" style="width:${prob}%"></div></div>
      <span class="scenario-pct">${prob}%</span>
    </div>
    <div class="scenario-detail">
      <ul>${reasons.map((r) => `<li>${r}</li>`).join('')}</ul>
      ${scenario.key_stat ? `<div class="scenario-key-stat">${scenario.key_stat}</div>` : ''}
    </div>
  `

  li.querySelector('.scenario-row-header').addEventListener('click', () => {
    const was = li.classList.contains('expanded')
    listEl.querySelectorAll('.scenario-row.expanded').forEach((r) => r.classList.remove('expanded'))
    if (!was) li.classList.add('expanded')
  })

  listEl.appendChild(li)
}

function applyMostLikely(scenarios, listEl) {
  let best = -1
  let bestIdx = 0
  scenarios.forEach((s, i) => {
    if (!s) return
    const p = s.probability ?? 0
    if (p > best) {
      best = p
      bestIdx = i
    }
  })
  listEl.querySelectorAll('.scenario-row').forEach((row) => row.classList.remove('most-likely'))
  const row = listEl.querySelector(`.scenario-row[data-index="${bestIdx}"]`)
  if (row) row.classList.add('most-likely')
}

function updateSimulateProgress(completed, total) {
  const el = document.getElementById('simulateProgressText')
  if (!el) return
  const t = total || 3
  const c = Math.min(completed, t)
  el.textContent = `Running scenario ${c}/${t}...`
}

function closeSimulateStream() {
  if (simulateEventSource) {
    simulateEventSource.close()
    simulateEventSource = null
  }
  if (simulateProgressSource) {
    simulateProgressSource.close()
    simulateProgressSource = null
  }
}

async function runSimulate() {
  if (simulateRunning) return

  const listEl = document.getElementById('scenarioTree')
  simulateRunning = true
  updateRunPredictButton()
  closeSimulateStream()

  try {
    const res = await fetch(`${API}/unified_state`)
    currentState = await res.json()
  } catch (_) {
    simulateRunning = false
    updateRunPredictButton()
    return
  }

  setPredictContext(currentState)
  expandPredictSection()
  setSimulateLoading(true)
  updateSimulateProgress(0, 3)
  listEl.innerHTML = ''
  thinkingBuffers = []
  activeThinkingIndex = -1
  clearPredictTerminal()

  const seedLabels = buildScenarioSeedLabels(currentState)
  await playPredictTerminalIntro(currentState)

  const scenarios = new Array(3).fill(null)
  const totalScenarios = scenarios.length

  simulateEventSource = new EventSource(`${API}/simulate/stream`)

  simulateProgressSource = new EventSource(`${API}/simulate/progress`)
  simulateProgressSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.total) {
        updateSimulateProgress(data.completed || 0, data.total)
      }
    } catch (_) {}
  }

  simulateEventSource.addEventListener('progress', (e) => {
    try {
      const data = JSON.parse(e.data)
      updateSimulateProgress(data.completed || 0, data.total || totalScenarios)
    } catch (_) {}
  })

  simulateEventSource.addEventListener('scenario_done', async (e) => {
    const { index, scenario, response_ms } = JSON.parse(e.data)
    if (response_ms != null && scenario.response_ms == null) {
      scenario.response_ms = response_ms
    }
    scenarios[index] = scenario
    addScenarioRow(scenario, index, listEl, false)
    const doneCount = scenarios.filter(Boolean).length
    updateSimulateProgress(doneCount, totalScenarios)

    const label = scenario.title || seedLabels[index] || `Scenario ${index + 1}`
    const t = ((scenario.response_ms ?? response_ms ?? 0) / 1000).toFixed(1)
    await delay(300)
    appendPredictTerminalLine(`→ [${index + 1}] ${label} — complete ${t}s`)
  })

  simulateEventSource.addEventListener('complete', async (e) => {
    const data = JSON.parse(e.data)
    const final = data.scenarios || scenarios.filter(Boolean)
    applyMostLikely(final, listEl)
    if (data.generated_ms) {
      document.getElementById('footerMeta').textContent =
        `4 models · ${(data.generated_ms / 1000).toFixed(1)}s · Wafer`
    }
    await delay(300)
    appendPredictTerminalLine(
      `→ Synthesis complete — ${data.generated_ms || 0}ms total`
    )
    closeSimulateStream()
    resetSimulateButton()
  })

  simulateEventSource.addEventListener('simulate_error', async (e) => {
    try {
      const { error } = JSON.parse(e.data)
      await delay(300)
      appendPredictTerminalLine(`→ Error: ${error || 'Simulation failed.'}`)
    } catch (_) {}
    closeSimulateStream()
    resetSimulateButton()
  })

  simulateEventSource.onerror = () => {
    if (simulateEventSource?.readyState === EventSource.CLOSED) {
      closeSimulateStream()
      resetSimulateButton()
    }
  }

  updateRunPredictButton()
}

async function fetchAll() {
  try {
    const [stateRes, insightRes] = await Promise.all([
      fetch(`${API}/unified_state`),
      fetch(`${API}/insight`)
    ])
    const state = await stateRes.json()
    const insight = await insightRes.json()
    updateAll(state, insight)
  } catch (_) {}
}

document.addEventListener('DOMContentLoaded', () => {
  setupCollapse()
  setupAgentCollapse()
  setupPredictCollapse()
  setInterval(fetchAll, 3000)
  setInterval(fetchDetectionFps, 2000)
  if (!insightUpdatedInterval) {
    insightUpdatedInterval = setInterval(updateInsightUpdatedLabel, 1000)
  }
  fetchAll()
  fetchDetectionFps()
})
