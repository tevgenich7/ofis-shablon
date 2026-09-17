// Панель офиса - локальный сервер.
// Ничего не устанавливает, не тянет из интернета, работает только на этом компьютере.
// Запускается кнопкой ЗАПУСК, слушает localhost и разговаривает с офисом через агентскую
// программу: Claude Code или Codex (OpenAI). Какая стоит на компьютере, ту и берёт;
// принудительно: OFFICE_AGENT=claude | codex.
//
// Разговоров может быть несколько (вкладки в панели). Каждый - со своей памятью и своим
// процессом агента: длинная задача не тянет контекст в следующую и не жжёт лимиты зря.

const http = require('http')
const fs = require('fs')
const path = require('path')
const { spawn, spawnSync } = require('child_process')
const crypto = require('crypto')

const KOREN = path.resolve(__dirname, '..')       // корень офиса
const PORT = Number(process.env.OFFICE_PORT || 4477)
const PANEL = __dirname
const KLYUCHI_PANELI = {
  DEEPGRAM_API_KEY: { dlina: 40 },
  GEMINI_API_KEY: {}, FAL_KEY: {}, PEXELS_API_KEY: {},
  UNSPLASH_API_KEY: {}, PIXABAY_API_KEY: {}, TELEGRAM_BOT_TOKEN: {},
}

const uuid = () => crypto.randomUUID()

// ── состояние ────────────────────────────────────────────────────────────────
let agent = null                 // { vid: 'claude' | 'codex', bin }
const codexLaunchers = new Map()
const razgovory = new Map()      // id -> разговор
let vstrechaOtpravlena = false
// Последний известный остаток лимита аккаунта: приходит от Codex во время работы.
let limity = null
let podnyatijBotaPodryad = 0
let botZablokirovan = false
let proverkaBota = null

const BOT_OTNOSITELNO = path.join('scripts', 'tg', 'ofis-bot.py')
const BOT_POISK = 'ofis-bot.py'

function najtiPython3() {
  for (const kandidat of ['/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3']) {
    if (fs.existsSync(kandidat)) return kandidat
  }
  const rezultat = spawnSync('which', ['python3'], { encoding: 'utf8' })
  const kandidat = rezultat.status === 0 ? rezultat.stdout.trim().split(/\r?\n/)[0] : ''
  return kandidat && path.isAbsolute(kandidat) && fs.existsSync(kandidat) ? kandidat : null
}

function spisokBotov() {
  const r = spawnSync('pgrep', ['-f', BOT_POISK], { encoding: 'utf8' })
  if (r.status !== 0) return []
  return r.stdout.split(/\s+/).map(Number).filter(Number.isInteger).map((pid) => {
    const ps = spawnSync('ps', ['-o', 'stat=', '-p', String(pid)], { encoding: 'utf8' })
    return { pid, stat: ps.status === 0 ? ps.stdout.trim() : '' }
  })
}

function poslednieStrokiZhurnala() {
  try {
    const d = fs.readFileSync(path.join(PANEL, 'zhurnal-bota.log'))
    return d.subarray(Math.max(0, d.length - 16 * 1024)).toString('utf8').split(/\r?\n/).slice(-80).join('\n')
  } catch { return '' }
}

function sostoyanieBota() {
  const boty = spisokBotov()
  const zamorozhen = boty.some((b) => b.stat.includes('T'))
  const zhiv = boty.length > 0 && !zamorozhen
  return {
    zhiv,
    zamorozhen,
    zablokirovan: botZablokirovan,
    telegramNedostupen: zhiv && /ConnectionResetError/.test(poslednieStrokiZhurnala()),
  }
}

function obnovitSostoyanieBota() {
  const sostoyanie = sostoyanieBota()
  poslatVsem('bot', sostoyanie)
  return sostoyanie
}

function ubitBotov() {
  for (const { pid } of spisokBotov()) {
    try { process.kill(pid, 'SIGTERM') } catch {}
    // Замороженный процесс не обработает SIGTERM, пока не получит SIGCONT.
    try { process.kill(pid, 'SIGCONT') } catch {}
  }
}

const pauza = (ms) => new Promise((gotovo) => setTimeout(gotovo, ms))

function podnyatBota() {
  // Именно pgrep, а не ссылка на дочерний процесс: бот мог быть поднят прошлым
  // запуском панели и продолжает жить после её закрытия.
  if (spisokBotov().length) return false
  if (botZablokirovan || podnyatijBotaPodryad >= 5) {
    botZablokirovan = true
    return false
  }
  const skript = path.join(KOREN, BOT_OTNOSITELNO)
  if (!fs.existsSync(skript)) return console.log('[бот] не поднят: не найден файл бота.')
  const python = najtiPython3()
  if (!python) return console.log('[бот] не поднят: не найдена программа Python 3.')

  const zhurnal = path.join(PANEL, 'zhurnal-bota.log')
  const vyvod = fs.openSync(zhurnal, 'a')
  try {
    const bot = spawn(python, ['-u', skript], {
      cwd: KOREN,
      detached: true,
      stdio: ['ignore', vyvod, vyvod],
    })
    bot.unref()
    podnyatijBotaPodryad += 1
  } catch (e) {
    console.error(`[бот] не удалось запустить; журнал: ${zhurnal}`, e)
    return false
  } finally {
    fs.closeSync(vyvod)
  }
  return true
}

function prismotretZaBotom() {
  let sostoyanie = sostoyanieBota()
  if (sostoyanie.zamorozhen) {
    ubitBotov()
    // SIGTERM уже отправлен, но даём ядру убрать старый процесс до нового запуска.
    // Если он всё ещё висит, это именно тот случай, когда его надо убрать принудительно.
    setTimeout(() => {
      for (const { pid } of spisokBotov()) { try { process.kill(pid, 'SIGKILL') } catch {} }
      setTimeout(() => { podnyatBota(); obnovitSostoyanieBota() }, 50).unref()
    }, 300).unref()
  } else if (!sostoyanie.zhiv) {
    podnyatBota()
  } else {
    // Бот пережил полную проверку: это не серия мгновенных падений.
    podnyatijBotaPodryad = 0
  }
  obnovitSostoyanieBota()
}

async function perezapustitBota() {
  botZablokirovan = false
  podnyatijBotaPodryad = 0
  ubitBotov()
  await pauza(300)
  // На случай, если обычное завершение зависло, убираем только найденные процессы бота.
  for (const { pid } of spisokBotov()) { try { process.kill(pid, 'SIGKILL') } catch {} }
  await pauza(50)
  podnyatBota()
  return obnovitSostoyanieBota()
}

function novyjRazgovor(imya) {
  const id = uuid().slice(0, 8)
  razgovory.set(id, {
    id,
    imya: imya || 'Разговор',
    sessionId: null,       // id нити у агента (claude: session, codex: thread)
    proc: null,
    zanyat: false,
    ochered: [],
    poslednijOtvet: '',
    istoriya: [],          // [{kto:'ya'|'ofis', text}] - чтобы вкладка восстанавливалась
    podpischiki: [],
    sozdan: Date.now(),
  })
  return razgovory.get(id)
}

// Разговоры живут в памяти процесса, а панель теперь закрывается сама. Чтобы человек
// не терял историю, складываем её на диск: без живых объектов (процесс, подписчики,
// очередь) - только то, что имеет смысл после перезапуска.
const FAJL_RAZGOVOROV = path.join(PANEL, 'razgovory.json')

function sohranitRazgovory() {
  try {
    const dannye = [...razgovory.values()].map((r) => ({
      id: r.id, imya: r.imya, sessionId: r.sessionId, istoriya: r.istoriya, sozdan: r.sozdan,
    }))
    fs.writeFileSync(FAJL_RAZGOVOROV, JSON.stringify(dannye), 'utf8')
  } catch {}
}

function podnyatRazgovory() {
  let dannye = []
  try { dannye = JSON.parse(fs.readFileSync(FAJL_RAZGOVOROV, 'utf8')) } catch { return }
  if (!Array.isArray(dannye)) return
  for (const d of dannye) {
    if (!d || !d.id) continue
    razgovory.set(d.id, {
      id: d.id,
      imya: d.imya || 'Разговор',
      sessionId: d.sessionId || null,
      proc: null,
      zanyat: false,
      ochered: [],
      poslednijOtvet: '',
      istoriya: Array.isArray(d.istoriya) ? d.istoriya : [],
      podpischiki: [],
      sozdan: d.sozdan || Date.now(),
    })
  }
}

function spisokRazgovorov() {
  return [...razgovory.values()].map((r) => ({
    id: r.id, imya: r.imya, zanyat: r.zanyat, soobshenij: r.istoriya.length, sozdan: r.sozdan,
  }))
}

function poslat(R, sobytie, dannye) {
  const stroka = `event: ${sobytie}\ndata: ${JSON.stringify(dannye)}\n\n`
  for (const r of R.podpischiki) { try { r.write(stroka) } catch {} }
}

// события, которые касаются всей панели, а не одной вкладки
function poslatVsem(sobytie, dannye) {
  for (const R of razgovory.values()) poslat(R, sobytie, dannye)
}

// ── какая агентская программа стоит ──────────────────────────────────────────
function najtiBin(imya) {
  const kand = process.platform === 'win32'
    ? [`${imya}.cmd`, `${imya}.exe`, imya]
    : [`/opt/homebrew/bin/${imya}`, `/usr/local/bin/${imya}`, `${process.env.HOME}/.local/bin/${imya}`, imya,
       ...(imya === 'codex' ? ['/Applications/ChatGPT.app/Contents/Resources/codex'] : [])]  // codex внутри приложения ChatGPT на маке
  for (const k of kand) {
    if (k.includes('/') || k.includes('\\')) { if (fs.existsSync(k)) return k; continue }
    const gde = spawnSync(process.platform === 'win32' ? 'where' : 'which', [k], { encoding: 'utf8' })
    if (gde.status === 0 && gde.stdout.trim()) return gde.stdout.trim().split(/\r?\n/)[0]
  }
  return null
}

function najtiAgenta() {
  if (process.env.CLAUDE_BIN && fs.existsSync(process.env.CLAUDE_BIN)) return { vid: 'claude', bin: process.env.CLAUDE_BIN }
  if (process.env.CODEX_BIN && fs.existsSync(process.env.CODEX_BIN)) return { vid: 'codex', bin: process.env.CODEX_BIN }
  const hochu = (process.env.OFFICE_AGENT || '').toLowerCase()
  const poryadok = hochu === 'codex' ? ['codex', 'claude'] : hochu === 'claude' ? ['claude', 'codex'] : ['codex', 'claude']
  for (const vid of poryadok) { const bin = najtiBin(vid); if (bin) return { vid, bin } }
  return null
}

// ── запуск офиса ─────────────────────────────────────────────────────────────
function podnyat(R, prodolzhit) {
  agent = najtiAgenta()
  if (!agent) {
    poslat(R, 'beda', {
      zagolovok: 'Не вижу агентской программы на этом компьютере',
      chto: 'Офис работает поверх Codex или Claude Code, а ни того, ни другого тут пока нет.',
      shagi: ['Открой инструкцию УСТАНОВКА.md в папке офиса', 'Пройди первые шаги оттуда', 'Вернись и открой офис ещё раз'],
    })
    return null
  }
  if (agent.vid === 'codex') return podnyatCodex(R, prodolzhit)
  const bin = agent.bin

  const argv = [
    '-p',
    '--input-format', 'stream-json',
    '--output-format', 'stream-json',
    '--verbose',
    '--include-partial-messages',
    '--permission-mode', 'acceptEdits',
  ]
  if (prodolzhit && R.sessionId) argv.push('--resume', R.sessionId)
  else { R.sessionId = uuid(); argv.push('--session-id', R.sessionId) }

  const p = spawn(bin, argv, { cwd: KOREN, stdio: ['pipe', 'pipe', 'pipe'] })

  let hvost = ''
  p.stdout.on('data', (buf) => {
    hvost += buf.toString('utf8')
    const stroki = hvost.split('\n')
    hvost = stroki.pop()
    for (const s of stroki) { if (s.trim()) razobrat(R, s) }
  })
  p.stderr.on('data', (b) => process.stderr.write(b))
  p.on('exit', () => {
    R.proc = null; R.zanyat = false
    if (R.ochered.length) otpravitDalshe(R)
  })
  return p
}

// ── Codex: один процесс на одно сообщение, разговор держится через thread id ───
function podnyatCodex(R, prodolzhit) {
  // Панель может работать через Rosetta, хотя Codex установлен для Apple Silicon.
  // Проверяем родной запуск один раз; на Intel остаётся обычный способ.
  if (!codexLaunchers.has(agent.bin)) {
    const native = process.platform === 'darwin'
      ? spawnSync('/usr/bin/arch', ['-arm64', agent.bin, '--version'], { timeout: 5000, encoding: 'utf8' })
      : null
    codexLaunchers.set(agent.bin, native && native.status === 0
      ? { bin: '/usr/bin/arch', prefix: ['-arm64', agent.bin] }
      : { bin: agent.bin, prefix: [] })
  }
  const launcher = codexLaunchers.get(agent.bin)
  // --full-auto убран в codex 0.154: теперь песочница и политика согласований задаются явно
  // --dangerously-bypass-hook-trust: сторожа офиса (.codex/hooks) запускаются без ручного
  // одобрения через /hooks. Иначе Codex молча пропускает хуки, пока человек их не «доверил»,
  // и защита не работает. Проверено живьём 17.09.2026 (codex-cli 0.154).
  const argv = ['exec', '--json', '--skip-git-repo-check', '--dangerously-bypass-hook-trust',
                '-s', 'workspace-write', '-c', 'approval_policy="never"', '-C', KOREN]
  if (prodolzhit && R.sessionId) argv.push('resume', R.sessionId)
  const p = spawn(launcher.bin, [...launcher.prefix, ...argv], { cwd: KOREN, stdio: ['pipe', 'pipe', 'pipe'] })
  R.poslednijOtvet = ''
  let hvost = ''
  p.stdout.on('data', (buf) => {
    hvost += buf.toString('utf8')
    const stroki = hvost.split('\n')
    hvost = stroki.pop()
    for (const s of stroki) { if (s.trim()) razobratCodex(R, s) }
  })
  p.stderr.on('data', (b) => process.stderr.write(b))
  p.on('exit', (kod) => {
    if (hvost.trim()) razobratCodex(R, hvost)
    R.proc = null
    if (R.zanyat) {          // процесс кончился без turn.completed - отдаём, что есть
      R.zanyat = false
      zapomnitOtvet(R, R.poslednijOtvet)
      poslat(R, 'gotovo', { itog: R.poslednijOtvet, oshibka: kod !== 0, prichina: kod !== 0 ? `программа офиса закрылась с кодом ${kod}` : '' })
      obnovitVitrinu()
    }
    if (R.ochered.length) otpravitDalshe(R)
  })
  return p
}

// Техническая ругань агентской программы не должна попадать в ленту: человек видит
// «Ignoring malformed agent role definition» и решает, что офис сломался. Офис с ней
// всегда говорит по-русски, поэтому сообщение без единой русской буквы - служебное.
function tehnicheskoe(text) {
  if (!text) return false
  if (/[а-яА-ЯёЁ]/.test(text)) return false
  return /ignoring|malformed|deprecated|warning|unexpected argument|error|failed|may only contain/i.test(text)
    || text.length > 40
}

function zapomnitOtvet(R, text) {
  if (text && R.istoriya[R.istoriya.length - 1]?.text !== text) { R.istoriya.push({ kto: 'ofis', text }); sohranitRazgovory() }
}

function razobratCodex(R, stroka) {
  let s
  try { s = JSON.parse(stroka) } catch { return }
  // Codex сам присылает остаток лимита в событии token_count - бесплатно, попутно с работой.
  // Запоминаем и раздаём вкладкам; спрашивать отдельно не надо, это стоило бы запроса.
  if (s.type === 'token_count' || s.type === 'TokenCount') {
    const rl = s.rate_limits || s.info?.rate_limits
    const okno = rl?.primary || rl?.secondary
    if (okno && typeof okno.used_percent === 'number') {
      limity = {
        ispolzovano: Math.round(okno.used_percent),
        minutOkna: okno.window_duration_mins || okno.window_minutes || null,
        sbrosV: okno.resets_at || null,
      }
      poslatVsem('limity', limity)
    }
    return
  }

  if (s.type === 'thread.started') { R.sessionId = s.thread_id; poslat(R, 'zhiv', { session: R.sessionId }); return }
  const it = s.item
  if (s.type === 'item.started' && it) {
    if (it.type === 'command_execution') poslat(R, 'rabota', { chto: 'работаю с файлами' })
    if (it.type === 'file_change') poslat(R, 'rabota', { chto: 'пишу файлы' })
    if (it.type === 'web_search') poslat(R, 'rabota', { chto: 'смотрю в интернете' })
    if (it.type === 'mcp_tool_call') poslat(R, 'rabota', { chto: 'работаю' })
    return
  }
  if (s.type === 'item.completed' && it) {
    if (it.type === 'agent_message' && it.text) {
      if (tehnicheskoe(it.text)) { process.stderr.write('[служебное] ' + it.text + '\n'); return }
      R.poslednijOtvet = it.text
      zapomnitOtvet(R, it.text)
      poslat(R, 'otvet', { text: it.text })
    }
    if (it.type === 'file_change') for (const c of it.changes || []) poslat(R, 'rabota', { chto: `пишу ${korotko(c.path)}` })
    if (it.type === 'error') {
      const m = it.message || ''
      if (tehnicheskoe(m)) process.stderr.write('[служебное] ' + m + '\n')
      else poslat(R, 'otvet', { text: m || 'что-то пошло не так' })
    }
    return
  }
  if (s.type === 'turn.completed' || s.type === 'turn.failed' || s.type === 'error') {
    R.zanyat = false
    const prichina = s.type === 'turn.completed' ? '' : (s.error?.message || s.message || '')
    poslat(R, 'gotovo', { itog: R.poslednijOtvet, oshibka: s.type !== 'turn.completed', prichina })
    obnovitVitrinu()
    if (R.ochered.length) otpravitDalshe(R)
  }
}

// ── Claude Code: разбор потока stream-json ───────────────────────────────────
function razobrat(R, stroka) {
  let s
  try { s = JSON.parse(stroka) } catch { return }

  if (s.session_id) R.sessionId = s.session_id

  if (s.type === 'stream_event' && s.event?.type === 'content_block_delta') {
    const d = s.event.delta
    if (d?.type === 'text_delta') poslat(R, 'kusok', { text: d.text })
    return
  }

  if (s.type === 'assistant') {
    for (const blok of s.message?.content || []) {
      if (blok.type === 'text') {
        if (tehnicheskoe(blok.text)) { process.stderr.write('[служебное] ' + blok.text + '\n'); continue }
        zapomnitOtvet(R, blok.text); poslat(R, 'otvet', { text: blok.text })
      }
      if (blok.type === 'tool_use') poslat(R, 'rabota', { chto: podpis(blok) })
    }
    return
  }

  if (s.type === 'result') {
    R.zanyat = false
    // при ошибке отдаём её текст: панель покажет его человеку, а не молчаливое «готово»
    poslat(R, 'gotovo', { itog: s.result || '', oshibka: !!s.is_error, prichina: s.is_error ? (s.result || s.error || '') : '' })
    obnovitVitrinu()
    if (R.ochered.length) otpravitDalshe(R)
    return
  }

  if (s.type === 'system' && s.subtype === 'init') poslat(R, 'zhiv', { session: s.session_id })
}

// человеческая подпись под работу инструмента: клиенту не нужны имена тулов
function podpis(blok) {
  const n = blok.name
  const v = blok.input || {}
  if (n === 'Task') return `зову ${v.subagent_type || 'помощника'}`
  if (n === 'Read') return `читаю ${korotko(v.file_path)}`
  if (n === 'Write' || n === 'Edit') return `пишу ${korotko(v.file_path)}`
  if (n === 'Bash') return 'работаю с файлами'
  if (n === 'WebSearch' || n === 'WebFetch') return 'смотрю в интернете'
  if (n === 'Skill') return `берусь за «${v.skill || ''}»`
  return 'работаю'
}
const korotko = (p) => (p ? String(p).split(/[\\/]/).slice(-2).join('/') : '')

// ── отправка в офис ──────────────────────────────────────────────────────────
function otpravitDalshe(R) {
  if (R.zanyat || !R.ochered.length) return
  const text = R.ochered.shift()
  R.zanyat = true
  if (!R.proc || R.proc.exitCode !== null) R.proc = podnyat(R, !!R.sessionId)
  if (!R.proc) { R.zanyat = false; return }
  if (agent && agent.vid === 'codex') {
    R.proc.stdin.write(text); R.proc.stdin.end()   // codex читает задачу из stdin и ждёт его конца
  } else {
    const soobshenie = { type: 'user', message: { role: 'user', content: [{ type: 'text', text }] } }
    R.proc.stdin.write(JSON.stringify(soobshenie) + '\n')
  }
  poslat(R, 'dumayu', {})
}

// ── витрина: что уже сделано, чтобы клиент видел результат, а не логи ────────
function obnovitVitrinu() {
  poslatVsem('vitrina', sobratVitrinu())
  try { poslatVsem('ustanovka', sostoyanieUstanovki()); poslatVsem('podklyucheno', chtoPodklyucheno()) } catch {}
}

const KARTINKI = new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif'])
const VIDEO = new Set(['.mp4', '.mov', '.m4v'])

// Сотрудники кладут работы и в подпапки (results/rilsy/<дата>-<тема>/...), поэтому
// обходим папку вглубь. imya - путь относительно results/<папка>, по нему панель отдаёт файл.
function sobratFajly(dir, otn, out, glubina) {
  let zapisi = []
  try { zapisi = fs.readdirSync(dir, { withFileTypes: true }) } catch { return }
  for (const z of zapisi) {
    if (z.name.startsWith('.')) continue
    const polnyj = path.join(dir, z.name)
    const put = otn ? `${otn}/${z.name}` : z.name
    if (z.isDirectory()) { if (glubina < 4) sobratFajly(polnyj, put, out, glubina + 1); continue }
    if (!z.isFile()) continue
    let st
    try { st = fs.statSync(polnyj) } catch { continue }
    const r = path.extname(z.name).toLowerCase()
    out.push({
      imya: put, kogda: st.mtimeMs, razmer: st.size,
      vid: KARTINKI.has(r) ? 'kartinka' : VIDEO.has(r) ? 'video' : 'fajl',
    })
  }
}

function sobratVitrinu() {
  const papki = [
    ['rilsy', 'Ролики'], ['karuseli', 'Карусели'],
    ['kartinki', 'Картинки'], ['teksty', 'Тексты'], ['strategii', 'Стратегии'],
  ]
  const out = []
  for (const [p, imya] of papki) {
    const fajly = []
    sobratFajly(path.join(KOREN, 'results', p), '', fajly, 0)
    fajly.sort((a, b) => b.kogda - a.kogda)
    out.push({ papka: p, imya, fajly: fajly.slice(0, 12) })
  }
  return out
}

function prochitatPlan() {
  const f = path.join(KOREN, 'plan', 'kontent-plan.md')
  try { return fs.readFileSync(f, 'utf8') } catch { return '' }
}

// ── установка: журнал этапов и что уже подключено ────────────────────────────
function sostoyanieUstanovki() {
  const f = path.join(KOREN, 'team', 'ops', 'ustanovka-log.md')
  let text = ''
  try { text = fs.readFileSync(f, 'utf8') } catch { return { est: false, etapy: [], zakonchena: true } }
  const etapy = []
  for (const stroka of text.split('\n')) {
    const m = stroka.match(/^- \[([ xX])\]\s*этап\s*(\d+)\s*-\s*(.+)$/)
    if (!m) continue
    const nazvanie = m[3].trim()
    // Хвост в скобках говорит, чья доля в этапе: [она], [она + Тарас], [Тарас].
    // Нет пометки - считаем этап её. Этапы только Тараса встречу Технаря не зовут.
    const teg = nazvanie.match(/\[([^\]]*)\]\s*$/)
    const eyo = !teg || /она/i.test(teg[1])
    etapy.push({ nomer: Number(m[2]), gotovo: m[1].toLowerCase() === 'x', nazvanie, eyo })
  }
  if (!etapy.length) return { est: false, etapy: [], zakonchena: true, vstrecha: false }
  const eyoNezakrytyj = etapy.find((e) => !e.gotovo && e.eyo)
  const tekushchij = eyoNezakrytyj || etapy.find((e) => !e.gotovo)
  return {
    est: true, etapy,
    zakonchena: !tekushchij,                 // всё закрыто, панель прячет блок установки
    vstrecha: !!eyoNezakrytyj,               // Технарь встречает только когда есть её незакрытый шаг
    tekushchij: tekushchij ? tekushchij.nomer : null,
  }
}

// Что реально подключено. Значения ключей НЕ читаем и наружу не отдаём - только сам факт,
// что строка с таким именем в файле есть и она не пустая.
function chtoPodklyucheno() {
  const est = (imya) => {
    const gde = spawnSync(process.platform === 'win32' ? 'where' : 'which', [imya], { encoding: 'utf8' })
    return gde.status === 0 && !!gde.stdout.trim()
  }
  const klyuchi = {}
  try {
    const env = fs.readFileSync(path.join(KOREN, '.env'), 'utf8')
    for (const stroka of env.split('\n')) {
      const m = stroka.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)$/)
      if (m) klyuchi[m[1]] = m[2].trim().length > 0
    }
  } catch {}
  const botZhiv = (() => {
    const r = spawnSync('pgrep', ['-f', 'ofis-bot.py'], { encoding: 'utf8' })
    return r.status === 0 && !!r.stdout.trim()
  })()
  const knopka = fs.existsSync(path.join(process.env.HOME || '', 'Desktop', 'Офис.app'))
  const kopii = (() => {
    const r = spawnSync('git', ['remote'], { cwd: KOREN, encoding: 'utf8' })
    return r.status === 0 && !!r.stdout.trim()
  })()
  const gugl = fs.existsSync(path.join(KOREN, '.mcp-sheets', 'token.json'))
  return [
    { imya: 'Сборка роликов', gotovo: est('ffmpeg'), zachem: 'Монтажёр склеивает видео' },
    { imya: 'Карусели картинками', gotovo: est('magick'), zachem: 'Дизайнер собирает слайды' },
    { imya: 'Расшифровка речи', gotovo: !!klyuchi.DEEPGRAM_API_KEY, zachem: 'офис слышит, что сказано в дублях', klyuch: 'DEEPGRAM_API_KEY' },
    { imya: 'Картинки (Gemini)', gotovo: !!(klyuchi.GEMINI_API_KEY || klyuchi.GOOGLE_API_KEY), zachem: 'обложки, фоны, слайды', klyuch: 'GEMINI_API_KEY' },
    { imya: 'Картинки (FLUX)', gotovo: !!klyuchi.FAL_KEY, zachem: 'картинки посложнее, по кадру-образцу', klyuch: 'FAL_KEY' },
    { imya: 'Стоки', gotovo: !!(klyuchi.PEXELS_API_KEY || klyuchi.UNSPLASH_API_KEY || klyuchi.PIXABAY_API_KEY), zachem: 'перебивки в роликах и фоны', klyuch: 'PEXELS_API_KEY' },
    { imya: 'Гугл-документы', gotovo: gugl, zachem: 'таблицы, документы, формы, диск' },
    { imya: 'Бот в телеграме', gotovo: botZhiv, zachem: 'правки голосом с телефона' },
    { imya: 'Кнопка на рабочем столе', gotovo: knopka, zachem: 'офис открывается без терминала' },
    { imya: 'Копии офиса', gotovo: kopii, zachem: 'работа не живёт в одном экземпляре' },
  ]
}

function zapisatKlyuch(imya, syroe) {
  if (!Object.prototype.hasOwnProperty.call(KLYUCHI_PANELI, imya) || typeof syroe !== 'string') {
    return { ok: false, soobshenie: 'Выбери подключение из списка.' }
  }
  const znachenie = syroe.trim()
  if (!znachenie) return { ok: false, soobshenie: 'Вставь ключ целиком.' }
  if (/\s/.test(znachenie)) return { ok: false, soobshenie: 'Похоже, скопировалось лишнее, скопируй только сам ключ.' }
  const pravilo = KLYUCHI_PANELI[imya]
  if (pravilo.dlina && znachenie.length !== pravilo.dlina) {
    const dva = znachenie.length === pravilo.dlina * 2
    return { ok: false, soobshenie: dva
      ? `Получилось ${znachenie.length} символов, а у Deepgram ключ ровно ${pravilo.dlina}. Похоже, скопировались два ключа. Проверь, пожалуйста, что это один ключ.`
      : `Получилось ${znachenie.length} символов, а у Deepgram ключ ровно ${pravilo.dlina}. Проверь, пожалуйста, что это один ключ.` }
  }
  const fajl = path.join(KOREN, '.' + 'env')
  const vremennyj = path.join(KOREN, `.${process.pid}.${crypto.randomBytes(8).toString('hex')}.tmp`)
  try {
    let stroki = []
    try { stroki = fs.readFileSync(fajl, 'utf8').split(/\r?\n/) } catch (e) { if (e.code !== 'ENOENT') throw e }
    const novye = stroki.filter((s) => !s.startsWith(`${imya}=`))
    while (novye.length && novye[novye.length - 1] === '') novye.pop()
    novye.push(`${imya}=${znachenie}`)
    fs.writeFileSync(vremennyj, novye.join('\n') + '\n', { mode: 0o600 })
    fs.renameSync(vremennyj, fajl)
    fs.chmodSync(fajl, 0o600)
    return { ok: true, dlina: znachenie.length }
  } catch {
    try { fs.unlinkSync(vremennyj) } catch {}
    return { ok: false, soobshenie: 'Не получилось сохранить ключ. Попробуй ещё раз.' }
  }
}

// Первое слово в панели говорит офис, а не человек: она открывает панель и уже видит,
// что её встретили. Текст ниже человек не видит - это задание Технарю.
function vstretit(R) {
  const u = sostoyanieUstanovki()
  if (vstrechaOtpravlena || !u.est || !u.vstrecha) return
  vstrechaOtpravlena = true
  const zadanie = [
    'СЛУЖЕБНОЕ СООБЩЕНИЕ ПАНЕЛИ. Это не реплика владелицы, она пока ничего не писала.',
    'Офис только что открыт, установка не закончена: незакрытый этап № ' + u.tekushchij + '.',
    'Ты - Технарь. Прочитай team/agents/tehnar/ustanovka.md и team/ops/ustanovka-log.md.',
    'Твоё первое сообщение к ней строится так и никак иначе:',
    '1) поздоровайся; 2) представься по имени и скажи одной фразой, за что ты отвечаешь:',
    'переводишь всё техническое на человеческий язык и всегда рядом, если что-то непонятно -',
    'можно позвать по имени; 3) скажи, что вы сейчас вместе настроите офис и это займёт',
    'около двадцати минут, один раз; 4) дай ПЕРВЫЙ шаг - одно действие - и спроси, получилось ли.',
    'Больше одного шага в сообщении не давай. Список этапов ей не перечисляй.',
    'Экономь лимиты: не читай лишних файлов, в интернет не ходи, отвечай коротко.',
  ].join(' ')
  R.ochered.push(zadanie)
  otpravitDalshe(R)
}

// ── HTTP ─────────────────────────────────────────────────────────────────────
const TIPY = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
  '.svg': 'image/svg+xml', '.mp4': 'video/mp4', '.mov': 'video/quicktime', '.md': 'text/plain; charset=utf-8',
}

function telo(req) {
  return new Promise((res) => {
    let kuski = [], razmer = 0, zakonchen = false
    const pusto = () => { zakonchen = true; kuski = []; res({}) }
    req.on('data', (c) => {
      if (zakonchen) return
      razmer += c.length
      if (razmer > 80 * 1024 * 1024) { pusto(); req.destroy(); return }
      kuski.push(c)
    })
    req.on('error', pusto)
    req.on('aborted', pusto)
    req.on('end', () => {
      if (zakonchen) return
      try {
        const d = JSON.parse(Buffer.concat(kuski).toString('utf8'))
        res(d && typeof d === 'object' && !Array.isArray(d) ? d : {})
      } catch { res({}) }
      zakonchen = true; kuski = []
    })
  })
}

const otvetJson = (res, d) => { res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(d)) }

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, `http://localhost:${PORT}`)

  if (u.pathname === '/' || u.pathname === '/index.html') return otdat(res, path.join(PANEL, 'index.html'))
  if (u.pathname.startsWith('/assets/')) return otdat(res, path.join(PANEL, u.pathname.replace('/assets/', 'assets/')))

  // готовые работы - только из results, наружу ничего больше не отдаём
  // путь может быть вложенным (rilsy/<дата>-<тема>/файл.mp4), но выйти из results/ нельзя
  if (u.pathname.startsWith('/rabota/')) {
    let otn = ''
    try { otn = decodeURIComponent(u.pathname.replace('/rabota/', '')) } catch { res.writeHead(400); return res.end() }
    const baza = path.join(KOREN, 'results')
    const polnyj = path.resolve(baza, otn)
    if (!polnyj.startsWith(baza + path.sep)) { res.writeHead(403); return res.end() }
    if (!fs.existsSync(polnyj) || !fs.statSync(polnyj).isFile()) { res.writeHead(404); return res.end('файл не найден') }
    return otdat(res, polnyj)
  }

  // показать файл в Finder: офис дал ссылку - по клику открывается папка с файлом
  if (u.pathname === '/api/pokazat') {
    const otn = decodeURIComponent(u.searchParams.get('put') || '')
    const polnyj = path.resolve(KOREN, otn)
    if (!polnyj.startsWith(KOREN) || !fs.existsSync(polnyj)) { res.writeHead(404); return res.end('нет такого файла') }
    try {
      if (process.platform === 'darwin') spawn('open', ['-R', polnyj], { detached: true, stdio: 'ignore' }).unref()
      else if (process.platform === 'win32') spawn('explorer', ['/select,', polnyj], { detached: true, stdio: 'ignore' }).unref()
      else spawn('xdg-open', [path.dirname(polnyj)], { detached: true, stdio: 'ignore' }).unref()
    } catch {}
    return otvetJson(res, { ok: true })
  }

  // список вкладок
  if (u.pathname === '/api/razgovory') return otvetJson(res, { razgovory: spisokRazgovorov() })

  if (u.pathname === '/api/bot') return otvetJson(res, sostoyanieBota())

  if (u.pathname === '/api/bot/perezapustit' && req.method === 'POST') {
    return otvetJson(res, await perezapustitBota())
  }

  if (u.pathname === '/api/klyuch' && req.method === 'POST') {
    const d = await telo(req)
    const rezultat = zapisatKlyuch(d.imya, d.znachenie)
    if (rezultat.ok) poslatVsem('podklyucheno', chtoPodklyucheno())
    return otvetJson(res, rezultat)
  }

  // новая вкладка
  if (u.pathname === '/api/novyj' && req.method === 'POST') {
    const d = await telo(req)
    const R = novyjRazgovor(d.imya)
    poslatVsem('vkladki', { razgovory: spisokRazgovorov() })
    return otvetJson(res, { id: R.id })
  }

  // закрыть вкладку
  if (u.pathname === '/api/zakryt' && req.method === 'POST') {
    const d = await telo(req)
    const R = razgovory.get(d.id)
    if (R) {
      if (R.proc) { try { R.proc.kill() } catch {} }
      for (const p of R.podpischiki) { try { p.end() } catch {} }
      razgovory.delete(R.id)
    }
    poslatVsem('vkladki', { razgovory: spisokRazgovorov() })
    return otvetJson(res, { ok: true })
  }

  // поток одной вкладки
  if (u.pathname === '/api/potok') {
    const id = u.searchParams.get('razgovor')
    const R = razgovory.get(id) || novyjRazgovor('Установка')
    res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache', Connection: 'keep-alive' })
    res.write(': ok\n\n')
    R.podpischiki.push(res)
    res.write(`event: ya\ndata: ${JSON.stringify({ id: R.id, imya: R.imya })}\n\n`)
    res.write(`event: istoriya\ndata: ${JSON.stringify({ soobsheniya: R.istoriya })}\n\n`)
    res.write(`event: vkladki\ndata: ${JSON.stringify({ razgovory: spisokRazgovorov() })}\n\n`)
    res.write(`event: vitrina\ndata: ${JSON.stringify(sobratVitrinu())}\n\n`)
    res.write(`event: plan\ndata: ${JSON.stringify({ text: prochitatPlan() })}\n\n`)
    res.write(`event: ustanovka\ndata: ${JSON.stringify(sostoyanieUstanovki())}\n\n`)
    res.write(`event: podklyucheno\ndata: ${JSON.stringify(chtoPodklyucheno())}\n\n`)
    res.write(`event: bot\ndata: ${JSON.stringify(sostoyanieBota())}\n\n`)
    if (limity) res.write(`event: limity\ndata: ${JSON.stringify(limity)}\n\n`)
    otmenitZakrytie()
    req.on('close', () => {
      R.podpischiki = R.podpischiki.filter((r) => r !== res)
      mozhetPoraZakryvatsya()
    })
    setTimeout(() => vstretit(R), 400)   // офис здоровается первым, человеку писать не нужно
    return
  }

  if (u.pathname === '/api/skazat' && req.method === 'POST') {
    const d = await telo(req)
    const R = razgovory.get(d.razgovor)
    if (!R) return otvetJson(res, { ok: false, pochemu: 'нет такого разговора' })
    if (d.text) {
      R.istoriya.push({ kto: 'ya', text: d.text }); sohranitRazgovory()
      // имя вкладки - первые слова первой просьбы, чтобы вкладки различались на глаз
      if (R.istoriya.filter((s) => s.kto === 'ya').length === 1 && R.imya === 'Разговор') {
        R.imya = d.text.trim().split(/\s+/).slice(0, 4).join(' ').slice(0, 40)
        poslatVsem('vkladki', { razgovory: spisokRazgovorov() })
      }
      R.ochered.push(d.text)
      otpravitDalshe(R)
    }
    return otvetJson(res, { ok: true })
  }

  if (u.pathname === '/api/fajl' && req.method === 'POST') {
    const d = await telo(req)
    if (req.aborted) return
    const R = razgovory.get(d.razgovor)
    if (!R) return otvetJson(res, { ok: false, pochemu: 'Нет такого разговора. Обнови страницу.' })
    if (typeof d.imya !== 'string' || typeof d.dannye !== 'string'
        || d.dannye.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(d.dannye)) {
      return otvetJson(res, { ok: false, pochemu: 'Не получилось прочитать файл. Попробуй ещё раз.' })
    }
    let imya = d.imya.replace(/[\\/\x00-\x1f\x7f]/g, '').trim().replace(/^\.+/, '') || 'fajl'
    // Ограничиваем длину имени, оставляя место для метки при совпадении.
    imya = Array.from(imya).slice(0, 80).join('')
    const dannye = Buffer.from(d.dannye, 'base64')
    if (dannye.length > 60 * 1024 * 1024) return otvetJson(res, { ok: false, pochemu: 'Файл больше 60 МБ. Положи его в папку inbox вручную.' })
    try {
      const inbox = path.join(fs.realpathSync(KOREN), 'inbox')
      fs.mkdirSync(inbox, { recursive: true })
      if (fs.realpathSync(inbox) !== inbox) throw new Error('inbox path')
      const ext = path.extname(imya), osnova = path.basename(imya, ext)
      for (let n = 0; ; n++) {
        const kandidat = n ? `${osnova}-${Date.now()}-${n}${ext}` : imya
        const polnyj = path.resolve(inbox, kandidat)
        if (!polnyj.startsWith(inbox + path.sep)) throw new Error('file path')
        try {
          fs.writeFileSync(polnyj, dannye, { flag: 'wx' })
          imya = kandidat; break
        } catch (e) { if (e.code !== 'EEXIST') throw e }
      }
    } catch {
      return otvetJson(res, { ok: false, pochemu: 'Не удалось сохранить файл в офисе. Попробуй ещё раз.' })
    }
    R.istoriya.push({ kto: 'ya', text: `файл: ${imya}` }); sohranitRazgovory()
    R.ochered.push(`Файл лежит в ${JSON.stringify('inbox/' + imya)}. Посмотри, что это, и разбери по правилам офиса: медиа в knowledge/raw, скриншот статистики передай Маркетологу в цифры, текст в сырьё. Ничего не отправляй наружу; расшифровка только после отдельного согласия владелицы.`)
    otpravitDalshe(R)
    return otvetJson(res, { ok: true })
  }

  // «начать заново» внутри вкладки: новая нить, старая память забывается
  if (u.pathname === '/api/zanovo' && req.method === 'POST') {
    const d = await telo(req)
    const R = razgovory.get(d.razgovor)
    if (R) {
      if (R.proc) { try { R.proc.kill() } catch {} }
      R.proc = null; R.sessionId = null; R.ochered = []; R.zanyat = false; R.istoriya = []
    }
    return otvetJson(res, { ok: true })
  }

  res.writeHead(404); res.end('нет такой страницы')
})

function otdat(res, fajl) {
  fs.readFile(fajl, (e, d) => {
    if (e) { res.writeHead(404); return res.end('файл не найден') }
    res.writeHead(200, { 'Content-Type': TIPY[path.extname(fajl).toLowerCase()] || 'application/octet-stream' })
    res.end(d)
  })
}

// Порт мог остаться занят прошлым запуском: панель не закрывается сама, когда
// человек просто закрывает вкладку. Тогда значок с рабочего стола молча не открывает
// офис, и это выглядит как поломка. Освобождаем порт сами - один раз, не в цикле.
function osvoboditPort() {
  const r = spawnSync('lsof', ['-ti', `tcp:${PORT}`], { encoding: 'utf8' })
  if (r.status !== 0 || !r.stdout.trim()) return false
  const svoj = String(process.pid)
  let ubrali = false
  for (const stroka of r.stdout.split(/\s+/)) {
    const pid = Number(stroka)
    if (!Number.isInteger(pid) || String(pid) === svoj) continue
    try { process.kill(pid, 'SIGTERM'); ubrali = true } catch {}
  }
  if (!ubrali) return false
  // Даём старой панели закрыться по-хорошему, иначе убираем принудительно.
  const konec = Date.now() + 1500
  while (Date.now() < konec) {
    const e = spawnSync('lsof', ['-ti', `tcp:${PORT}`], { encoding: 'utf8' })
    if (e.status !== 0 || !e.stdout.trim()) return true
    spawnSync('sleep', ['0.1'])
  }
  for (const stroka of (spawnSync('lsof', ['-ti', `tcp:${PORT}`], { encoding: 'utf8' }).stdout || '').split(/\s+/)) {
    const pid = Number(stroka)
    if (Number.isInteger(pid) && String(pid) !== svoj) { try { process.kill(pid, 'SIGKILL') } catch {} }
  }
  spawnSync('sleep', ['0.3'])
  return true
}

// Закрыли последнюю вкладку - офис ждёт немного и выключается сам, освобождая порт.
// Пауза нужна, чтобы обычная перезагрузка страницы не гасила офис.
const PAUZA_PERED_ZAKRYTIEM = 20 * 1000
let tajmerZakrytiya = null

function estVkladki() {
  for (const R of razgovory.values()) if (R.podpischiki.length) return true
  return false
}

function otmenitZakrytie() {
  if (tajmerZakrytiya) { clearTimeout(tajmerZakrytiya); tajmerZakrytiya = null }
}

function mozhetPoraZakryvatsya() {
  otmenitZakrytie()
  if (estVkladki()) return
  tajmerZakrytiya = setTimeout(() => {
    if (estVkladki()) return
    // Работа в разгаре - не бросаем её на полпути, ждём следующей проверки.
    for (const R of razgovory.values()) if (R.zanyat) return mozhetPoraZakryvatsya()
    console.log('  Офис закрыт: вкладок не осталось.')
    zavrshitOfis()
  }, PAUZA_PERED_ZAKRYTIEM)
  tajmerZakrytiya.unref()
}

server.on('error', (e) => {
  if (e.code !== 'EADDRINUSE') throw e
  if (osvoboditPort()) {
    console.log('  Прошлый запуск офиса не закрылся - убрал его, открываю заново.')
    server.listen(PORT, '127.0.0.1')
    return
  }
  console.error(`\n  Не получилось открыть офис: порт ${PORT} занят чем-то ещё.\n`)
  process.exit(1)
})

podnyatRazgovory()

server.listen(PORT, '127.0.0.1', () => {
  console.log(`\n  Офис открыт: http://localhost:${PORT}\n  Чтобы закрыть - просто закрой это окно.\n`)
  prismotretZaBotom()
  proverkaBota = setInterval(prismotretZaBotom, 15 * 1000)
  proverkaBota.unref()
  if (process.env.BROWSER === 'none') return
  const otkryt = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'explorer' : 'xdg-open'
  try { spawn(otkryt, [`http://localhost:${PORT}`], { detached: true, stdio: 'ignore' }).unref() } catch {}
})

function zavrshitOfis() {
  sohranitRazgovory()
  if (proverkaBota) clearInterval(proverkaBota)
  server.close(() => process.exit(0))
  setTimeout(() => process.exit(0), 2000).unref()
}

process.once('SIGINT', zavrshitOfis)
process.once('SIGTERM', zavrshitOfis)
