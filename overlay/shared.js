const API = 'http://localhost:5001'
if (typeof window !== 'undefined') {
  window.API = API
}

const HOME_XG_PER90 = 2.1
const AWAY_XG_PER90 = 1.8

const FORMATION_433 = [
  { x: 50, y: 92 },
  { x: 14, y: 76 },
  { x: 36, y: 76 },
  { x: 64, y: 76 },
  { x: 86, y: 76 },
  { x: 22, y: 52 },
  { x: 50, y: 52 },
  { x: 78, y: 52 },
  { x: 20, y: 24 },
  { x: 50, y: 20 },
  { x: 80, y: 24 }
]

const PLAYER_SEASON_STATS = {
  Raya: { goals: 0, assists: 0, rating: 7.2 },
  White: { goals: 2, assists: 4, rating: 7.4 },
  Saliba: { goals: 1, assists: 0, rating: 7.6 },
  Gabriel: { goals: 2, assists: 1, rating: 7.5 },
  Zinchenko: { goals: 0, assists: 3, rating: 7.1 },
  Odegaard: { goals: 8, assists: 10, rating: 7.9 },
  Partey: { goals: 3, assists: 2, rating: 7.3 },
  Rice: { goals: 4, assists: 6, rating: 7.8 },
  Saka: { goals: 14, assists: 8, rating: 7.8 },
  Havertz: { goals: 9, assists: 4, rating: 7.4 },
  Martinelli: { goals: 11, assists: 5, rating: 7.6 },
  Ederson: { goals: 0, assists: 1, rating: 7.0 },
  Walker: { goals: 0, assists: 3, rating: 7.2 },
  Dias: { goals: 1, assists: 0, rating: 7.5 },
  Akanji: { goals: 2, assists: 1, rating: 7.3 },
  Gvardiol: { goals: 1, assists: 4, rating: 7.4 },
  Rodri: { goals: 6, assists: 5, rating: 7.7 },
  'De Bruyne': { goals: 4, assists: 12, rating: 7.9 },
  Silva: { goals: 5, assists: 7, rating: 7.6 },
  Mahrez: { goals: 8, assists: 9, rating: 7.5 },
  Haaland: { goals: 22, assists: 4, rating: 8.1 },
  Grealish: { goals: 6, assists: 8, rating: 7.4 }
}

const SUB_MINUTE_BAND = {
  0: 2, 45: 20, 50: 30, 55: 45, 60: 60,
  65: 75, 70: 85, 75: 80, 80: 70, 85: 90, 90: 95
}

const ZONE_MODIFIERS = {
  home_box: 1.25,
  away_box: 1.15,
  midfield: 1.0,
  unknown: 1.0
}

function teamShort(name) {
  if (!name) return '—'
  return name.split(' ')[0]
}

function possessionHome(state) {
  let poss = 50

  const visionPoss = state?.vision?.possession_home
  const statsPoss = state?.stats?.possession_home
  const history = state?.possession_history || []

  if (visionPoss && visionPoss > 5 && visionPoss < 95) {
    poss = visionPoss
  } else if (statsPoss && statsPoss > 5 && statsPoss < 95) {
    poss = statsPoss
  } else if (history.length >= 2) {
    const alpha = 0.3
    let ema = history[0]
    for (let i = 1; i < history.length; i++) {
      ema = alpha * history[i] + (1 - alpha) * ema
    }
    poss = Math.round(Math.max(30, Math.min(70, ema)))
  }

  return poss
}

function pressIntensityLevel(state) {
  const raw = (state?.vision?.pressing_intensity || 'low').toLowerCase()
  if (raw === 'high') return 2
  if (raw === 'medium') return 1
  return 0
}

function playerEnergy(minute) {
  return Math.max(0, Math.round(100 - (minute / 90) * 60))
}

function estimatedDistanceKm(minute) {
  return (minute * 0.13).toFixed(1)
}

function estimatedSprints(minute) {
  return Math.round(minute * 0.8)
}

function scenarioTimeEstimate(probability) {
  const p = Math.max(0, Math.min(100, probability || 0))
  return Math.max(1, Math.round(5 * (1 - p / 100) * 2 + 1))
}

function formatMatchContext(state) {
  const match = state.match || {}
  const vision = state.vision || {}
  const minute = match.minute ?? '—'
  const home = teamShort(match.team_home || 'Home').toUpperCase().slice(0, 3)
  const away = teamShort(match.team_away || 'Away').toUpperCase().slice(0, 3)
  const score = match.score || { home: 0, away: 0 }
  const ball = (vision.ball_zone || 'unknown').replace(/_/g, '_')
  const shape = (vision.team_shape || 'unknown').replace(/_/g, '_')
  return `Min ${minute} · ${home} ${score.home}-${score.away} ${away} · Ball: ${ball} · Shape: ${shape}`
}

function energyColor(pct) {
  if (pct >= 60) return '#2d8a4e'
  if (pct >= 30) return '#c9a227'
  return '#c8102e'
}

function truncateWords(text, maxWords = 15) {
  if (!text) return ''
  const words = text.trim().split(/\s+/)
  if (words.length <= maxWords) return words.join(' ')
  return words.slice(0, maxWords).join(' ') + '…'
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function closestMinuteBand(minute) {
  const keys = Object.keys(SUB_MINUTE_BAND).map(Number)
  const closest = keys.reduce((a, b) =>
    Math.abs(b - minute) < Math.abs(a - minute) ? b : a
  )
  return { band: closest, factor: SUB_MINUTE_BAND[closest] }
}

function timeFactor(minute) {
  if (minute < 45) return 0.7
  if (minute < 60) return 1.0
  if (minute < 75) return 1.2
  return 1.4
}

function computeGoalBreakdown(state) {
  const match = state.match || {}
  const stats = state.stats || {}
  const minute = match.minute || 0
  const possession = possessionHome(state)
  const liveXgHome = stats.live_xg_home || 0
  const liveXgAway = stats.live_xg_away || 0
  const minsRemaining = Math.max(0, 90 - minute)
  const tf = timeFactor(minute)
  const possFactor = (possession / 100) * 1.12

  let remainingXg
  let baseLabel
  if (liveXgHome > 0 || liveXgAway > 0) {
    remainingXg =
      Math.max(0, HOME_XG_PER90 - liveXgHome) + Math.max(0, AWAY_XG_PER90 - liveXgAway)
    baseLabel = `(${HOME_XG_PER90}−${liveXgHome.toFixed(1)})+(${AWAY_XG_PER90}−${liveXgAway.toFixed(1)}) xG left`
  } else {
    const homeRate = (HOME_XG_PER90 / 90) * (possession / 50)
    const awayRate = (AWAY_XG_PER90 / 90) * ((100 - possession) / 50)
    remainingXg = (homeRate + awayRate) * minsRemaining
    baseLabel = `${HOME_XG_PER90}/90 min rate × ${minsRemaining}′ remaining`
  }

  const adjustedXg = remainingXg * possFactor * tf
  const prob = Math.round((1 - Math.exp(-adjustedXg)) * 100)

  return {
    prob,
    steps: [
      `Base xG rate: ${baseLabel}`,
      `Possession factor: ${possession}% × 1.12`,
      `Time factor: ×${tf.toFixed(2)} (${minute < 45 ? 'early game' : minute < 75 ? 'mid game' : 'late clusters'})`,
      `Result: ${prob}%`
    ]
  }
}

function computeSubBreakdown(state) {
  const match = state.match || {}
  const stats = state.stats || {}
  const minute = match.minute || 0
  const subsMade = stats.subs_made_home || 0
  const remaining = Math.max(0, 5 - subsMade)
  const { band, factor } = closestMinuteBand(minute)
  const minsSinceSub = subsMade === 0 ? minute : Math.max(0, minute - 45 * subsMade)

  let prob = 0
  if (remaining > 0) prob = factor

  return {
    prob,
    steps: [
      `Minutes since last sub: ${minsSinceSub}′`,
      `Remaining subs: ${remaining}/5`,
      `Minute band factor: ${factor}% (band ${band}′)`,
      `Result: ${prob}%`
    ]
  }
}

function computeShotBreakdown(state) {
  const match = state.match || {}
  const stats = state.stats || {}
  const vision = state.vision || {}
  const minute = match.minute || 0
  const possession = possessionHome(state)
  const shots = stats.shots_home || 0
  const onTarget = stats.shots_on_target_home || 0
  const zone = vision.ball_zone || 'unknown'
  const zoneMod = ZONE_MODIFIERS[zone] ?? 1.0
  const minsRemaining = Math.max(0, 90 - minute)
  const rate = minute > 0 ? onTarget / minute : 0.15
  const expected = rate * minsRemaining * (possession / 50) * zoneMod
  const prob = Math.round((1 - Math.exp(-expected)) * 100)

  return {
    prob,
    steps: [
      `Current rate: ${onTarget}/${shots || '—'} this match`,
      `Ball zone modifier: ${zone} ×${zoneMod.toFixed(2)}`,
      `Result: ${prob}%`
    ]
  }
}

function getFormationPos(player) {
  const idx = player.formation_index ?? 0
  return FORMATION_433[idx] || FORMATION_433[0]
}

if (typeof module !== 'undefined') {
  module.exports = {
    API,
    FORMATION_433,
    PLAYER_SEASON_STATS,
    teamShort,
    possessionHome,
    pressIntensityLevel,
    playerEnergy,
    estimatedDistanceKm,
    estimatedSprints,
    scenarioTimeEstimate,
    formatMatchContext,
    energyColor,
    truncateWords,
    delay,
    computeGoalBreakdown,
    computeSubBreakdown,
    computeShotBreakdown,
    getFormationPos
  }
}
