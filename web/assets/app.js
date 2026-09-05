// Lógica do painel do ClipRadar.
// Extraído de web/index.html. Inclui as traduções (pt/en/es), a
// navegação entre telas, o upload, o acompanhamento dos jobs, a
// biblioteca de clips e o envio de feedback.

/* =====================================================================
   TRADUÇÕES
===================================================================== */
const translations = {
  pt: {
    nav_create: "Criar projeto", nav_projects: "Meus projetos", nav_library: "Biblioteca de clips",
    nav_brand: "Brand Kit", nav_analytics: "Analytics", nav_settings: "Configurações", nav_soon: "em breve",
    user_settings: "Configurações", user_signout: "Sair",
    greeting_title: "Olá! Vamos criar seu próximo clip?",
    greeting_subtitle: "Envie um vídeo ou cole um link pra começar.",
    dropzone_title: "Clique ou arraste um arquivo de vídeo",
    dropzone_formats: "Aceita .mp4, .mov, .mkv, .webm",
    youtube_download_btn: "Baixar link",
    folder_toggle_show: "Ou escolher um vídeo já salvo no servidor",
    folder_toggle_hide: "Ocultar vídeos do servidor",
    label_folder_video: "Vídeos no servidor",
    label_mode: "O que gerar", mode_montage: "Montagem única", mode_separate: "Clipes separados",
    label_format: "Formato", format_vertical: "Vertical", format_horizontal: "Horizontal",
    label_platform: "Plataforma", platform_none: "Sem preferência",
    label_preset: "Estilo de edição", preset_clean: "Clean", preset_impact: "Impact", preset_streamer: "Streamer",
    mode_review: "Revisão manual", review_title: "Revisar e editar",
    label_trim_start: "Início", label_trim_end: "Fim",
    label_transcript: "Transcrição",
    transcript_hint: "Clique numa frase pra pular o preview até ali. Segure Shift e clique em outra pra selecionar um trecho e ajustar o clipe.",
    label_layout: "Layout",
    layout_gameplay_full: "Gameplay cheio", layout_gameplay_facecam: "Gameplay + facecam", layout_facecam_focus: "Facecam em foco",
    layout_blur_background: "Fundo borrado",
    library_title: "Biblioteca de clips", library_subtitle: "Tudo que você já gerou fica aqui.",
    library_empty: "Você ainda não gerou nenhum clip. Crie um projeto pra começar.",
    library_download: "Baixar", library_open: "Abrir",
    expires_today: "Expira hoje", expires_in: "Expira em", expires_days: "dias",
    usage_title: "Uso do mês", usage_of: "de", usage_minutes: "min",
    usage_plan_free: "Plano Grátis", usage_plan_pro: "Plano Pro",
    usage_upgrade: "Ver planos", usage_exhausted: "Seus minutos do mês acabaram.",
    library_count: "clip(s) salvos",
    review_render_btn: "Renderizar", review_rendering: "Renderizando...",
    dirty_banner: "Alterações ainda não renderizadas",
    review_download: "Baixar clip",
    review_no_candidates: "Nenhum candidato encontrado nesse vídeo.",
    label_subtitle_style: "Legenda",
    style_classic: "Clássico", style_bold_yellow: "Negrito amarelo", style_minimal_top: "Minimalista", style_boxed: "Caixa preta",
    label_captions: "Legendas queimadas",
    btn_generate: "Analisar e gerar clip",
    recent_title: "Projetos recentes",
    empty_recent_title: "Nenhum projeto ainda",
    empty_recent_body: "Envie seu primeiro vídeo acima — os projetos gerados nesta sessão aparecem aqui.",
    processing_title: "Preparando seu clip",
    processing_subtitle: "Isso pode levar alguns minutos, dependendo do tamanho do vídeo.",
    step_prepared: "Vídeo preparado",
    step_transcribed: "Áudio transcrito",
    step_analyzed: "Momentos analisados",
    step_editing: "Edição e legendas sendo preparadas",
    step_done: "Resultado pronto",
    processing_disclaimer: "As etapas acima refletem o andamento real do processamento no servidor.",
    results_title: "Seus clips",
    back_to_home: "Novo vídeo",
    panel_format: "Formato", panel_layout: "Estilo de edição", panel_subtitle: "Legenda", panel_title: "Título",
    panel_title_placeholder: "Dê um título pra esse clip...",
    action_download_clip: "Baixar clip",
    action_download_thumb: "Baixar thumbnail",
    action_save_draft: "Salvar como rascunho",
    action_approve: "Aprovar", action_reject: "Rejeitar", action_edit: "Editar",
    reason_question: "O que ficou ruim?", reason_skip: "Pular",
    reason_bad_start: "Começou errado", reason_bad_end: "Terminou errado",
    reason_boring: "Momento chato", reason_no_context: "Sem contexto",
    reason_bad_framing: "Enquadramento", reason_bad_captions: "Legenda errada",
    reason_duplicate: "Repetido", reason_other: "Outro",
    label_transcript: "Transcrição (clique numa palavra pra mover o preview)",
    transcript_empty: "Sem transcrição disponível pra esse clip.",
    label_trim: "Início / Fim do clip",
    mark_start: "Usar tempo atual como início",
    mark_end: "Usar tempo atual como fim",
    label_clip_layout: "Layout do enquadramento",
    layout_gameplay_full: "Gameplay",
    layout_gameplay_facecam: "Gameplay + Facecam",
    layout_facecam_focus: "Facecam em foco",
    layout_blur_background: "Fundo borrado",
    preset_streamer: "Streamer",
    dirty_notice: "Você mudou algo — clique em \"Renderizar novamente\" pra aplicar.",
    rerender_btn: "Renderizar novamente",
    rerendering: "Renderizando...",
    rerender_error: "Erro ao renderizar esse clip.",
    action_saved_draft: "Salvo como rascunho ✓",
    action_regenerate: "Aplicar e gerar novamente",
    tag_clutch: "Clutch", tag_reaction: "Reação", tag_funny: "Engraçado", tag_strong_quote: "Fala forte",
    tag_gameplay: "Gameplay", tag_conversation: "Conversa", tag_generic: "Momento",
    why_label: "Por que esse momento:",
    reason_hook: "começa forte", reason_emotion: "reação intensa", reason_intensity: "gameplay agitado",
    reason_surprise: "virada brusca", reason_ending: "termina em alta", reason_narrative: "contexto claro na fala",
    reason_clarity: "ritmo visual bom", reason_retention: "prende a atenção",
    reason_fallback: "pontuação acima da média do vídeo", reason_join: " e ",
    no_good_moments: "Nenhum momento com qualidade suficiente foi encontrado nesse vídeo.",
    processing_failed: "Falha no processamento. Tente novamente.",
    connection_lost: "Perdi a conexão com o servidor durante o processamento.",
    generate_error_fallback: "Erro ao iniciar processamento.",
    upload_error: "Erro ao enviar o arquivo.",
    upload_uploading: "Enviando arquivo...",
    youtube_url_missing: "Cole um link antes de baixar.",
    youtube_downloading: "Baixando...",
    youtube_download_error: "Erro ao baixar o vídeo.",
    status_loading: "carregando...",
    status_queue: (n) => `${n} vídeo(s) disponível(is)`,
    status_no_videos: "nenhum vídeo enviado ainda",
    status_error: "erro ao conectar na API",
    toast_generated: "Clip gerado com sucesso!",
    soon_title: "Em breve",
    soon_body: "Esse recurso ainda está em desenvolvimento.",
    soon_close: "Entendi",
  },
  en: {
    nav_create: "New project", nav_projects: "My projects", nav_library: "Clip library",
    nav_brand: "Brand Kit", nav_analytics: "Analytics", nav_settings: "Settings", nav_soon: "soon",
    user_settings: "Settings", user_signout: "Sign out",
    greeting_title: "Hi! Ready to create your next clip?",
    greeting_subtitle: "Upload a video or paste a link to get started.",
    dropzone_title: "Click or drag a video file",
    dropzone_formats: "Accepts .mp4, .mov, .mkv, .webm",
    youtube_download_btn: "Fetch link",
    folder_toggle_show: "Or choose a video already saved on the server",
    folder_toggle_hide: "Hide server videos",
    label_folder_video: "Videos on server",
    label_mode: "What to generate", mode_montage: "Single montage", mode_separate: "Separate clips",
    label_format: "Format", format_vertical: "Vertical", format_horizontal: "Horizontal",
    label_platform: "Platform", platform_none: "No preference",
    label_preset: "Editing style", preset_clean: "Clean", preset_impact: "Impact", preset_streamer: "Streamer",
    mode_review: "Manual review", review_title: "Review & edit",
    label_trim_start: "Start", label_trim_end: "End",
    label_transcript: "Transcript",
    transcript_hint: "Click a phrase to jump the preview there. Hold Shift and click another to select a range and adjust the clip.",
    label_layout: "Layout",
    layout_gameplay_full: "Full gameplay", layout_gameplay_facecam: "Gameplay + facecam", layout_facecam_focus: "Facecam focus",
    layout_blur_background: "Blurred background",
    library_title: "Clip library", library_subtitle: "Everything you've generated lives here.",
    library_empty: "You haven't generated any clips yet. Create a project to start.",
    library_download: "Download", library_open: "Open",
    expires_today: "Expires today", expires_in: "Expires in", expires_days: "days",
    usage_title: "Monthly usage", usage_of: "of", usage_minutes: "min",
    usage_plan_free: "Free plan", usage_plan_pro: "Pro plan",
    usage_upgrade: "See plans", usage_exhausted: "You've used all your minutes this month.",
    library_count: "saved clip(s)",
    review_render_btn: "Render", review_rendering: "Rendering...",
    dirty_banner: "Changes not rendered yet",
    review_download: "Download clip",
    review_no_candidates: "No candidates found in this video.",
    label_subtitle_style: "Captions",
    style_classic: "Classic", style_bold_yellow: "Bold yellow", style_minimal_top: "Minimal", style_boxed: "Black box",
    label_captions: "Burned-in captions",
    btn_generate: "Analyze & generate clip",
    recent_title: "Recent projects",
    empty_recent_title: "No projects yet",
    empty_recent_body: "Upload your first video above — projects generated this session show up here.",
    processing_title: "Preparing your clip",
    processing_subtitle: "This can take a few minutes depending on the video length.",
    step_prepared: "Video prepared",
    step_transcribed: "Audio transcribed",
    step_analyzed: "Moments analyzed",
    step_editing: "Editing & captions being prepared",
    step_done: "Result ready",
    processing_disclaimer: "The steps above reflect the real server-side progress.",
    results_title: "Your clips",
    back_to_home: "New video",
    panel_format: "Format", panel_layout: "Editing style", panel_subtitle: "Captions", panel_title: "Title",
    panel_title_placeholder: "Give this clip a title...",
    action_download_clip: "Download clip",
    action_download_thumb: "Download thumbnail",
    action_save_draft: "Save as draft",
    action_approve: "Approve", action_reject: "Reject", action_edit: "Edit",
    reason_question: "What went wrong?", reason_skip: "Skip",
    reason_bad_start: "Bad start", reason_bad_end: "Bad ending",
    reason_boring: "Boring moment", reason_no_context: "No context",
    reason_bad_framing: "Framing", reason_bad_captions: "Wrong captions",
    reason_duplicate: "Duplicate", reason_other: "Other",
    action_saved_draft: "Saved as draft ✓",
    action_regenerate: "Apply & regenerate",
    tag_clutch: "Clutch", tag_reaction: "Reaction", tag_funny: "Funny", tag_strong_quote: "Strong quote",
    tag_gameplay: "Gameplay", tag_conversation: "Conversation", tag_generic: "Moment",
    why_label: "Why this moment:",
    reason_hook: "strong opening", reason_emotion: "intense reaction", reason_intensity: "busy gameplay",
    reason_surprise: "sudden turn", reason_ending: "ends on a high", reason_narrative: "clear spoken context",
    reason_clarity: "good visual pacing", reason_retention: "holds attention",
    reason_fallback: "scored above this video's average", reason_join: " and ",
    no_good_moments: "No moment with enough quality was found in this video.",
    processing_failed: "Processing failed. Please try again.",
    connection_lost: "Lost connection to the server during processing.",
    generate_error_fallback: "Error starting processing.",
    upload_error: "Error uploading the file.",
    upload_uploading: "Uploading file...",
    youtube_url_missing: "Paste a link before fetching.",
    youtube_downloading: "Downloading...",
    youtube_download_error: "Error downloading the video.",
    status_loading: "loading...",
    status_queue: (n) => `${n} video(s) available`,
    status_no_videos: "no videos uploaded yet",
    status_error: "error connecting to API",
    toast_generated: "Clip generated successfully!",
    soon_title: "Coming soon",
    soon_body: "This feature is still in development.",
    soon_close: "Got it",
  },
  es: {
    nav_create: "Nuevo proyecto", nav_projects: "Mis proyectos", nav_library: "Biblioteca de clips",
    nav_brand: "Brand Kit", nav_analytics: "Analytics", nav_settings: "Configuración", nav_soon: "pronto",
    user_settings: "Configuración", user_signout: "Cerrar sesión",
    greeting_title: "¡Hola! ¿Creamos tu próximo clip?",
    greeting_subtitle: "Sube un video o pega un enlace para empezar.",
    dropzone_title: "Haz clic o arrastra un archivo de video",
    dropzone_formats: "Acepta .mp4, .mov, .mkv, .webm",
    youtube_download_btn: "Descargar enlace",
    folder_toggle_show: "O elige un video ya guardado en el servidor",
    folder_toggle_hide: "Ocultar videos del servidor",
    label_folder_video: "Videos en el servidor",
    label_mode: "Qué generar", mode_montage: "Montaje único", mode_separate: "Clips separados",
    label_format: "Formato", format_vertical: "Vertical", format_horizontal: "Horizontal",
    label_platform: "Plataforma", platform_none: "Sin preferencia",
    label_preset: "Estilo de edición", preset_clean: "Clean", preset_impact: "Impact", preset_streamer: "Streamer",
    mode_review: "Revisión manual", review_title: "Revisar y editar",
    label_trim_start: "Inicio", label_trim_end: "Fin",
    label_transcript: "Transcripción",
    transcript_hint: "Haz clic en una frase para saltar la vista previa ahí. Mantén Shift y haz clic en otra para seleccionar un tramo y ajustar el clip.",
    label_layout: "Diseño",
    layout_gameplay_full: "Gameplay completo", layout_gameplay_facecam: "Gameplay + facecam", layout_facecam_focus: "Facecam en foco",
    layout_blur_background: "Fondo desenfocado",
    library_title: "Biblioteca de clips", library_subtitle: "Todo lo que has generado está aquí.",
    library_empty: "Aún no has generado ningún clip. Crea un proyecto para empezar.",
    library_download: "Descargar", library_open: "Abrir",
    expires_today: "Expira hoy", expires_in: "Expira en", expires_days: "días",
    usage_title: "Uso del mes", usage_of: "de", usage_minutes: "min",
    usage_plan_free: "Plan Gratis", usage_plan_pro: "Plan Pro",
    usage_upgrade: "Ver planes", usage_exhausted: "Se acabaron tus minutos del mes.",
    library_count: "clip(s) guardados",
    review_render_btn: "Renderizar", review_rendering: "Renderizando...",
    dirty_banner: "Cambios aún no renderizados",
    review_download: "Descargar clip",
    review_no_candidates: "No se encontraron candidatos en este video.",
    label_subtitle_style: "Subtítulos",
    style_classic: "Clásico", style_bold_yellow: "Negrita amarillo", style_minimal_top: "Minimalista", style_boxed: "Caja negra",
    label_captions: "Subtítulos incrustados",
    btn_generate: "Analizar y generar clip",
    recent_title: "Proyectos recientes",
    empty_recent_title: "Aún no hay proyectos",
    empty_recent_body: "Sube tu primer video arriba — los proyectos generados en esta sesión aparecen aquí.",
    processing_title: "Preparando tu clip",
    processing_subtitle: "Esto puede tardar varios minutos según el tamaño del video.",
    step_prepared: "Video preparado",
    step_transcribed: "Audio transcrito",
    step_analyzed: "Momentos analizados",
    step_editing: "Edición y subtítulos en preparación",
    step_done: "Resultado listo",
    processing_disclaimer: "Los pasos de arriba reflejan el progreso real del servidor.",
    results_title: "Tus clips",
    back_to_home: "Nuevo video",
    panel_format: "Formato", panel_layout: "Estilo de edición", panel_subtitle: "Subtítulos", panel_title: "Título",
    panel_title_placeholder: "Dale un título a este clip...",
    action_download_clip: "Descargar clip",
    action_download_thumb: "Descargar thumbnail",
    action_save_draft: "Guardar como borrador",
    action_approve: "Aprobar", action_reject: "Rechazar", action_edit: "Editar",
    reason_question: "¿Qué salió mal?", reason_skip: "Saltar",
    reason_bad_start: "Mal inicio", reason_bad_end: "Mal final",
    reason_boring: "Momento aburrido", reason_no_context: "Sin contexto",
    reason_bad_framing: "Encuadre", reason_bad_captions: "Subtítulos",
    reason_duplicate: "Repetido", reason_other: "Otro",
    action_saved_draft: "Guardado como borrador ✓",
    action_regenerate: "Aplicar y regenerar",
    tag_clutch: "Clutch", tag_reaction: "Reacción", tag_funny: "Gracioso", tag_strong_quote: "Frase fuerte",
    tag_gameplay: "Gameplay", tag_conversation: "Conversación", tag_generic: "Momento",
    why_label: "Por qué este momento:",
    reason_hook: "empieza fuerte", reason_emotion: "reacción intensa", reason_intensity: "gameplay agitado",
    reason_surprise: "giro brusco", reason_ending: "termina en alto", reason_narrative: "contexto claro en el habla",
    reason_clarity: "buen ritmo visual", reason_retention: "mantiene la atención",
    reason_fallback: "puntuación por encima del promedio del video", reason_join: " y ",
    no_good_moments: "No se encontró ningún momento con calidad suficiente en este video.",
    processing_failed: "Falló el procesamiento. Intenta de nuevo.",
    connection_lost: "Se perdió la conexión con el servidor durante el procesamiento.",
    generate_error_fallback: "Error al iniciar el procesamiento.",
    upload_error: "Error al subir el archivo.",
    upload_uploading: "Subiendo archivo...",
    youtube_url_missing: "Pega un enlace antes de descargar.",
    youtube_downloading: "Descargando...",
    youtube_download_error: "Error al descargar el video.",
    status_loading: "cargando...",
    status_queue: (n) => `${n} video(s) disponible(s)`,
    status_no_videos: "aún no hay videos subidos",
    status_error: "error al conectar con la API",
    toast_generated: "¡Clip generado con éxito!",
    soon_title: "Próximamente",
    soon_body: "Esta función todavía está en desarrollo.",
    soon_close: "Entendido",
  },
};

function detectLang() {
  const supported = ['pt', 'en', 'es'];
  const browserLangs = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || 'en'];
  for (const lang of browserLangs) {
    const short = lang.slice(0, 2).toLowerCase();
    if (supported.includes(short)) return short;
  }
  return 'en';
}
const LANG = detectLang();
const T = translations[LANG];
document.documentElement.lang = LANG === 'pt' ? 'pt-BR' : LANG;

// Monta o "por que esse momento" a partir dos sinais do Content Score.
// Não usa IA e não custa nada — os números já vêm calculados do backend.
// Pega os dois sinais mais fortes acima de 65; se nenhum passar, usa o
// texto genérico em vez de inventar uma justificativa.
const REASON_SIGNALS = [
  ['hook', 'reason_hook'], ['emotional_reaction', 'reason_emotion'],
  ['gameplay_intensity', 'reason_intensity'], ['surprise', 'reason_surprise'],
  ['ending_quality', 'reason_ending'], ['narrative_context', 'reason_narrative'],
  ['visual_clarity', 'reason_clarity'], ['retention_potential', 'reason_retention'],
];

function buildReason(clip) {
  // Se a IA gerou uma explicação editorial, ela é melhor que a nossa.
  if (clip.edit_plan && clip.edit_plan.explanation) return clip.edit_plan.explanation;

  const b = clip.breakdown;
  if (!b) return null;

  const strong = REASON_SIGNALS
    .map(([key, tKey]) => ({ value: Number(b[key]) || 0, label: T[tKey] }))
    .filter(s => s.value >= 65)
    .sort((a, b2) => b2.value - a.value)
    .slice(0, 2)
    .map(s => s.label);

  if (!strong.length) return T.reason_fallback;
  return strong.join(T.reason_join) + '.';
}

const CLIP_TYPE_TAG_KEY = {
  clutch: 'tag_clutch', reaction: 'tag_reaction', funny: 'tag_funny', strong_quote: 'tag_strong_quote',
  gameplay: 'tag_gameplay', conversation: 'tag_conversation', generic: 'tag_generic',
};

function applyStaticTranslations() {
  const map = {
    navCreateLabel: 'nav_create', navProjectsLabel: 'nav_projects', navLibraryLabel: 'nav_library',
    navBrandLabel: 'nav_brand', navAnalyticsLabel: 'nav_analytics', navSettingsLabel: 'nav_settings',
    navSoon1: 'nav_soon', navSoon2: 'nav_soon', navSoon3: 'nav_soon',
    userSettingsItem: 'user_settings', userSignOutItem: 'user_signout',
    greetingTitle: 'greeting_title', greetingSubtitle: 'greeting_subtitle',
    dropzoneTitle: 'dropzone_title', dropzoneFormats: 'dropzone_formats',
    youtubeDownloadBtn: 'youtube_download_btn', labelFolderVideo: 'label_folder_video',
    labelMode: 'label_mode', labelFormat: 'label_format', labelPlatform: 'label_platform',
    labelPreset: 'label_preset', labelSubtitleStyle: 'label_subtitle_style', labelCaptions: 'label_captions',
    generateBtn: 'btn_generate', recentTitle: 'recent_title',
    processingTitle: 'processing_title', processingSubtitle: 'processing_subtitle',
    processingDisclaimer: 'processing_disclaimer',
    resultsTitle: 'results_title', backToHomeBtn: 'back_to_home',
    reviewTitle: 'review_title', backToHomeFromReviewBtn: 'back_to_home',
    labelTrimStart: 'label_trim_start', labelTrimEnd: 'label_trim_end', labelTranscript: 'label_transcript',
    soonModalTitle: 'soon_title', soonModalBody: 'soon_body', soonModalClose: 'soon_close',
  };
  for (const [id, key] of Object.entries(map)) {
    const el = document.getElementById(id);
    if (el) el.textContent = T[key];
  }
  document.getElementById('folderToggle').textContent = T.folder_toggle_show;
  document.getElementById('statusPill').textContent = T.status_loading;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (T[key]) el.textContent = T[key];
  });
}
applyStaticTranslations();

/* =====================================================================
   ESTADO GERAL
===================================================================== */
let selectedMode = 'montage';
let selectedOrientation = 'vertical';
let selectedPlatform = 'sem_preferencia';
// Sempre 'impact': liga zoom pontual e destaque de palavra. O 'clean'
// desligava os dois, que em short-form é sempre pior.
const selectedPreset = 'impact';
let recentProjects = []; // histórico só desta sessão (sem back-end persistente)
let currentClips = [];   // clips do resultado atualmente exibido
let currentClipIndex = 0;
let lastVideoName = null;
let pollTimer = null;

const els = {
  sidebar: document.getElementById('sidebar'),
  sidebarToggle: document.getElementById('sidebarToggle'),
  videoSelect: document.getElementById('videoSelect'),
  modeTabs: document.getElementById('modeTabs'),
  orientationTabs: document.getElementById('orientationTabs'),
  platformTabs: document.getElementById('platformTabs'),
  subtitleStyleSelect: document.getElementById('subtitleStyleSelect'),
  captionsCheckbox: document.getElementById('captionsCheckbox'),
  generateBtn: document.getElementById('generateBtn'),
  errorBox: document.getElementById('errorBox'),
  statusPill: document.getElementById('statusPill'),
  recentContainer: document.getElementById('recentContainer'),
  stepsList: document.getElementById('stepsList'),
  clipList: document.getElementById('clipList'),
  clipPreviewVideo: document.getElementById('clipPreviewVideo'),
  clipWhyBox: document.getElementById('clipWhyBox'),
  clipPanel: document.getElementById('clipPanel'),
};

function setView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view' + name.charAt(0).toUpperCase() + name.slice(1)).classList.add('active');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  if (name === 'home') document.getElementById('navProjects').classList.add('active');
  if (name === 'library') document.getElementById('navLibrary').classList.add('active');
  els.sidebar.classList.remove('open');
}

function showToast(message, type = 'success') {
  const region = document.getElementById('toastRegion');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  region.appendChild(toast);
  setTimeout(() => toast.remove(), 4200);
}

/* ---------- Menu mobile / dropdown do usuário / modal "em breve" ---------- */
els.sidebarToggle.addEventListener('click', () => els.sidebar.classList.toggle('open'));

const userDropdown = document.getElementById('userDropdown');
document.getElementById('userAvatarBtn').addEventListener('click', () => userDropdown.classList.toggle('open'));
document.addEventListener('click', (e) => {
  if (!e.target.closest('.user-menu')) userDropdown.classList.remove('open');
});

const soonModal = document.getElementById('soonModal');
function openSoonModal() { soonModal.classList.add('open'); }
document.getElementById('soonModalClose').addEventListener('click', () => soonModal.classList.remove('open'));
soonModal.addEventListener('click', (e) => { if (e.target === soonModal) soonModal.classList.remove('open'); });
document.getElementById('navBrandLabel').closest('.nav-item').addEventListener('click', openSoonModal);
document.getElementById('navAnalyticsLabel').closest('.nav-item').addEventListener('click', openSoonModal);
document.getElementById('navSettingsLabel').closest('.nav-item').addEventListener('click', openSoonModal);
document.getElementById('userSettingsItem').addEventListener('click', openSoonModal);
document.getElementById('userSignOutItem').addEventListener('click', async () => {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/login';
});

// Confirma que tem sessão válida antes de mostrar o painel — se não tiver
// (ou expirou), manda pro login em vez de deixar a tela "quebrada"
(async function checkAuth() {
  try {
    const res = await fetch('/api/auth/me');
    if (!res.ok) throw new Error('não autenticado');
  } catch (e) {
    window.location.href = '/login';
  }
})();
document.getElementById('navCreate').addEventListener('click', () => setView('home'));
document.getElementById('navProjects').addEventListener('click', () => setView('home'));
loadUsage();
document.getElementById('navLibrary').addEventListener('click', () => {
  setView('library');
  loadLibrary();
});

// Avisar ANTES de apagar. Sumir sem aviso é o que gera raiva de verdade.
function expiryBadge(days) {
  if (days === null || days === undefined) return '';
  const soon = days <= 2;
  const text = days <= 0 ? T.expires_today : `${T.expires_in} ${days} ${T.expires_days}`;
  return `<div class="expiry-badge ${soon ? 'soon' : ''}">${text}</div>`;
}

// Consumo do mês, mostrado no topo. O usuário precisa saber onde está antes
// de enviar um vídeo longo — não depois de esperar o processamento.
async function loadUsage() {
  const pill = document.getElementById('statusPill');
  if (!pill) return;
  try {
    const res = await fetch('/api/usage');
    if (!res.ok) return;
    const u = await res.json();
    const planLabel = u.plan === 'pro' ? T.usage_plan_pro : T.usage_plan_free;
    pill.innerHTML = `${planLabel} · ${Math.round(u.minutes_left)} ${T.usage_minutes}`;
    pill.title = `${T.usage_title}: ${Math.round(u.minutes_used)} ${T.usage_of} ${u.minutes_total} ${T.usage_minutes}`;
    pill.classList.toggle('exhausted', u.exhausted);
  } catch (e) { /* silencioso: não é crítico pro fluxo */ }
}

async function loadLibrary() {
  const grid = document.getElementById('libraryGrid');
  document.getElementById('libraryTitle').textContent = T.library_title;
  grid.innerHTML = `<p class="muted">...</p>`;
  try {
    const res = await fetch('/api/clips');
    if (!res.ok) throw new Error('falha ao carregar');
    const data = await res.json();
    document.getElementById('librarySubtitle').textContent =
      data.total ? `${data.total} ${T.library_count}` : T.library_subtitle;

    if (!data.clips.length) {
      grid.innerHTML = `<p class="muted">${T.library_empty}</p>`;
      return;
    }
    grid.innerHTML = data.clips.map(c => `
      <div class="library-item">
        <video src="${c.video}" ${c.thumbnail ? `poster="${c.thumbnail}"` : ''} controls preload="none"></video>
        <div class="library-meta">
          ${expiryBadge(c.expires_in_days)}
          <div class="name">${c.filename}</div>
          <div class="library-actions">
            <a class="btn btn-secondary" href="${c.video}" download>${T.library_download}</a>
            <a class="btn btn-ghost" href="${c.video}" target="_blank">${T.library_open}</a>
          </div>
        </div>
      </div>`).join('');
  } catch (e) {
    grid.innerHTML = `<p class="muted">${T.library_empty}</p>`;
  }
}
document.getElementById('backToHomeBtn').addEventListener('click', () => setView('home'));

/* ---------- Tabs genéricas ---------- */
function setupTabs(container, onSelect) {
  container.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      container.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      onSelect(tab.dataset.value);
    });
  });
}
setupTabs(els.modeTabs, v => selectedMode = v);
setupTabs(els.orientationTabs, v => selectedOrientation = v);
setupTabs(els.platformTabs, v => selectedPlatform = v);

/* ---------- Fonte do vídeo: dropzone / link / pasta do servidor ---------- */
const uploadDrop = document.getElementById('uploadDrop');
const uploadInput = document.getElementById('uploadInput');
const dropzoneTitleEl = document.getElementById('dropzoneTitle');
const youtubeUrlInput = document.getElementById('youtubeUrlInput');
const youtubeDownloadBtn = document.getElementById('youtubeDownloadBtn');
const folderToggle = document.getElementById('folderToggle');
const folderPicker = document.getElementById('folderPicker');
let folderOpen = false;

uploadDrop.addEventListener('click', () => uploadInput.click());
uploadDrop.addEventListener('dragover', (e) => { e.preventDefault(); uploadDrop.style.borderColor = 'var(--accent-lime)'; });
uploadDrop.addEventListener('dragleave', () => { uploadDrop.style.borderColor = ''; });
uploadDrop.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadDrop.style.borderColor = '';
  if (e.dataTransfer.files.length) {
    uploadInput.files = e.dataTransfer.files;
    uploadInput.dispatchEvent(new Event('change'));
  }
});

uploadInput.addEventListener('change', async () => {
  const file = uploadInput.files[0];
  if (!file) return;
  dropzoneTitleEl.textContent = T.upload_uploading;
  try {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/api/videos/upload', { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || T.upload_error);
    lastVideoName = data.video_name;
    dropzoneTitleEl.textContent = T.dropzone_title;
    await loadVideos();
    els.videoSelect.value = data.video_name;
    await runGenerate(data.video_name);
  } catch (e) {
    dropzoneTitleEl.textContent = T.dropzone_title;
    showToast(e.message, 'error');
  }
});

folderToggle.addEventListener('click', () => {
  folderOpen = !folderOpen;
  folderPicker.classList.toggle('open', folderOpen);
  folderToggle.textContent = folderOpen ? T.folder_toggle_hide : T.folder_toggle_show;
});

youtubeDownloadBtn.addEventListener('click', async () => {
  const url = youtubeUrlInput.value.trim();
  if (!url) { showToast(T.youtube_url_missing, 'error'); return; }
  youtubeDownloadBtn.disabled = true;
  youtubeDownloadBtn.textContent = T.youtube_downloading;
  try {
    const res = await fetch('/api/videos/from-youtube', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || T.youtube_download_error);

    const poll = setInterval(async () => {
      const statusRes = await fetch(`/api/videos/download-status/${data.job_id}`);
      const statusData = await statusRes.json();
      if (statusData.status === 'running') return;
      clearInterval(poll);
      youtubeDownloadBtn.disabled = false;
      youtubeDownloadBtn.textContent = T.youtube_download_btn;
      if (statusData.status === 'error') { showToast(statusData.error || T.youtube_download_error, 'error'); return; }
      lastVideoName = statusData.video_name;
      youtubeUrlInput.value = '';
      await loadVideos();
      els.videoSelect.value = statusData.video_name;
      await runGenerate(statusData.video_name);
    }, 3000);
  } catch (e) {
    youtubeDownloadBtn.disabled = false;
    youtubeDownloadBtn.textContent = T.youtube_download_btn;
    showToast(e.message, 'error');
  }
});

async function loadVideos() {
  try {
    const res = await fetch('/api/videos');
    const data = await res.json();
    els.videoSelect.innerHTML = '';
    data.videos.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name; opt.textContent = name;
      els.videoSelect.appendChild(opt);
    });
    els.statusPill.textContent = data.videos.length === 0 ? T.status_no_videos : T.status_queue(data.videos.length);
  } catch (e) {
    els.statusPill.textContent = T.status_error;
  }
}

/* ---------- Processamento (etapas REAIS, vindas do servidor) ---------- */
const STEP_ORDER = ['prepared', 'transcribed', 'analyzed', 'editing', 'done'];
const STEP_LABEL_KEYS = { prepared: 'step_prepared', transcribed: 'step_transcribed', analyzed: 'step_analyzed', editing: 'step_editing', done: 'step_done' };
function serverStepToBucket(step, status) {
  if (status === 'done') return 'done';
  if (step === 'transcribing') return 'transcribed';
  if (step === 'scoring') return 'analyzed';
  if (step === 'rendering') return 'editing';
  return 'prepared'; // queued, detecting, ou desconhecido
}
function renderSteps(currentBucket) {
  const currentIdx = STEP_ORDER.indexOf(currentBucket);
  els.stepsList.innerHTML = STEP_ORDER.map((key, idx) => {
    const state = idx < currentIdx ? 'done' : (idx === currentIdx ? 'active' : '');
    const icon = state === 'done' ? '✓' : (idx + 1);
    return `<div class="step-row ${state}"><div class="dot">${icon}</div><span class="label">${T[STEP_LABEL_KEYS[key]]}</span></div>`;
  }).join('');
}

async function runGenerate(videoName) {
  lastVideoName = videoName;
  setView('processing');
  renderSteps('prepared');

  try {
    const res = await fetch('/api/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        video_name: videoName, mode: selectedMode, orientation: selectedOrientation,
        platform: selectedPlatform, burn_captions: els.captionsCheckbox.checked,
        subtitle_style: els.subtitleStyleSelect.value, preset: selectedPreset,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || T.generate_error_fallback);
    pollJob(data.job_id);
  } catch (e) {
    showToast(e.message, 'error');
    setView('home');
  }
}

// Guardado pra que o feedback de cada clipe saiba de qual processamento veio.
let currentJobId = null;

function pollJob(jobId) {
  currentJobId = jobId;
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();

      if (data.status === 'running') {
        renderSteps(serverStepToBucket(data.step, data.status));
        return;
      }

      clearInterval(pollTimer);

      if (data.status === 'error') {
        showToast(data.error || T.processing_failed, 'error');
        setView('home');
        return;
      }

      renderSteps('done');
      setTimeout(() => showResults(data), 350);
    } catch (e) {
      clearInterval(pollTimer);
      showToast(T.connection_lost, 'error');
      setView('home');
    }
  }, 2000);
}

/* ---------- Resultados (3 colunas) ---------- */
function normalizeClips(data) {
  if (data.mode === 'separate') return data.clips || [];
  if (!data.final_video) return [];
  return [{
    clip_id: 'montagem', score: Math.max(0, ...((data.preview_cards || []).map(c => c.score))) || 0,
    duration_seconds: data.duration_seconds, video: data.final_video, thumbnail: data.thumbnail,
    edit_plan: data.edit_plan, is_montage: true,
  }];
}

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return '';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function showResults(data) {
  currentClips = normalizeClips(data);
  currentClipIndex = 0;

  if (!currentClips.length) {
    showToast(T.no_good_moments, 'error');
    setView('home');
    return;
  }

  showToast(T.toast_generated, 'success');
  recentProjects.unshift({
    video_name: lastVideoName, thumbnail: currentClips[0].thumbnail,
    clip_count: currentClips.length, saved: false,
  });
  renderRecent();

  renderClipList();
  selectClip(0);
  setView('results');
}

function renderClipList() {
  els.clipList.innerHTML = currentClips.map((c, idx) => {
    const tagKey = c.edit_plan ? CLIP_TYPE_TAG_KEY[c.edit_plan.clip_type] : null;
    const tagHtml = tagKey ? `<span class="badge badge-tag">${T[tagKey]}</span>` : '';
    const status = c.reviewStatus || 'pending';
    return `
      <div class="clip-list-item ${idx === currentClipIndex ? 'selected' : ''} ${status === 'rejected' ? 'rejected' : ''}" data-idx="${idx}">
        <img class="thumb" src="${c.thumbnail || ''}" onerror="this.style.visibility='hidden'">
        <div class="info">
          <div class="info-top">
            <span class="badge badge-score">${Math.round(c.score)}</span>
            ${tagHtml}
          </div>
          <div class="title">${c.is_montage ? T.results_title : (c.clip_id || '')}</div>
          <div class="duration">${formatDuration(c.duration_seconds)}</div>
          <div class="clip-actions">
            <button class="clip-action-btn approve ${status === 'approved' ? 'active' : ''}" data-action="approve" data-idx="${idx}" title="${T.action_approve}" aria-label="${T.action_approve}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M4 12l5 5L20 6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
            <button class="clip-action-btn reject ${status === 'rejected' ? 'active' : ''}" data-action="reject" data-idx="${idx}" title="${T.action_reject}" aria-label="${T.action_reject}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
            </button>
            <button class="clip-action-btn edit" data-action="edit" data-idx="${idx}" title="${T.action_edit}" aria-label="${T.action_edit}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M4 20l1-4.4L15.6 5 19 8.4 8.4 19 4 20z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');

  els.clipList.querySelectorAll('.clip-list-item').forEach(item => {
    item.addEventListener('click', () => selectClip(parseInt(item.dataset.idx, 10)));
  });
  els.clipList.querySelectorAll('.clip-action-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const idx = parseInt(btn.dataset.idx, 10);
      const action = btn.dataset.action;
      const clip = currentClips[idx];
      if (action === 'approve') {
        const wasApproved = clip.reviewStatus === 'approved';
        clip.reviewStatus = wasApproved ? 'pending' : 'approved';
        if (!wasApproved) sendClipFeedback(clip, 'approved');
      } else if (action === 'reject') {
        const wasRejected = clip.reviewStatus === 'rejected';
        clip.reviewStatus = wasRejected ? 'pending' : 'rejected';
        if (!wasRejected) {
          sendClipFeedback(clip, 'rejected');
          renderClipList();
          askRejectionReason(clip, idx);
          return;
        }
      } else if (action === 'edit') {
        selectClip(idx);
        setTimeout(() => document.getElementById('clipTitleInput')?.focus(), 50);
        return;
      }
      renderClipList();
    });
  });
}

// Envia o voto sem travar a interface: se a rede falhar, o usuário nem
// percebe — o dado é útil, mas não é crítico pro fluxo dele.
async function sendClipFeedback(clip, verdict, reason = null) {
  try {
    await fetch('/api/clips/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        verdict, reason,
        clip_id: clip.clip_id || null,
        job_id: currentJobId || null,
        score: clip.score ?? null,
        category: clip.category || null,
        candidate_type: clip.candidate_type || null,
        duration_seconds: clip.duration_seconds ?? null,
        signals: clip.breakdown || null,
      }),
    });
  } catch (e) { /* silencioso de propósito */ }
}

const REJECTION_REASONS = [
  'bad_start', 'bad_end', 'boring', 'no_context',
  'bad_framing', 'bad_captions', 'duplicate', 'other',
];

// Um clique, sem campo de texto. Texto livre quase ninguém preenche.
function askRejectionReason(clip, idx) {
  const existing = document.getElementById('reasonPrompt');
  if (existing) existing.remove();

  const box = document.createElement('div');
  box.id = 'reasonPrompt';
  box.className = 'card';
  box.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:200;max-width:min(520px,92vw);box-shadow:0 12px 40px rgba(0,0,0,0.5)';
  box.innerHTML = `
    <div style="font-size:0.9rem;margin-bottom:12px">${T.reason_question}</div>
    <div style="display:flex;flex-wrap:wrap;gap:8px">
      ${REJECTION_REASONS.map(r =>
        `<button class="btn btn-secondary" data-reason="${r}" style="font-size:0.78rem;padding:6px 12px">${T['reason_' + r]}</button>`
      ).join('')}
      <button class="btn btn-ghost" data-reason="" style="font-size:0.78rem;padding:6px 12px">${T.reason_skip}</button>
    </div>`;
  document.body.appendChild(box);

  box.querySelectorAll('button').forEach(b => {
    b.addEventListener('click', () => {
      const reason = b.dataset.reason;
      if (reason) sendClipFeedback(clip, 'rejected', reason);
      box.remove();
    });
  });

  // Some sozinho: não pode virar obstáculo pra quem só quer seguir usando.
  setTimeout(() => box.remove(), 12000);
}

function selectClip(idx) {
  currentClipIndex = idx;
  const clip = currentClips[idx];
  els.clipList.querySelectorAll('.clip-list-item').forEach((item, i) => {
    item.classList.toggle('selected', i === idx);
  });
  els.clipPreviewVideo.src = clip.video;

  const reason = buildReason(clip);
  if (reason) {
    els.clipWhyBox.style.display = 'block';
    els.clipWhyBox.innerHTML = `<strong>${T.why_label}</strong>${reason}`;
  } else {
    els.clipWhyBox.style.display = 'none';
  }

  renderClipPanel(clip);
}

function renderClipPanel(clip) {
  const defaultTitle = clip.edit_plan && clip.edit_plan.highlight_words && clip.edit_plan.highlight_words.length
    ? clip.edit_plan.highlight_words.join(' ')
    : '';

  els.clipPanel.innerHTML = `
    <div class="panel-group">
      <span class="field-label">${T.panel_format}</span>
      <div class="badge badge-muted">${selectedOrientation === 'vertical' ? T.format_vertical : T.format_horizontal}${selectedPlatform !== 'sem_preferencia' ? ' · ' + selectedPlatform : ''}</div>
    </div>
    <div class="panel-group">
      <span class="field-label">${T.panel_layout}</span>
      <div class="badge badge-muted">${T.preset_impact}</div>
    </div>
    <div class="panel-group">
      <span class="field-label">${T.panel_subtitle}</span>
      <div class="badge badge-muted">${els.captionsCheckbox.checked ? els.subtitleStyleSelect.selectedOptions[0].textContent : '—'}</div>
    </div>
    <div class="panel-group">
      <span class="field-label">${T.panel_title}</span>
      <input type="text" id="clipTitleInput" placeholder="${T.panel_title_placeholder}" value="${defaultTitle}">
    </div>
    <div class="panel-actions">
      <a class="btn btn-secondary" id="downloadClipBtn" href="${clip.video}" download>${T.action_download_clip}</a>
      ${clip.thumbnail ? `<a class="btn btn-secondary" href="${clip.thumbnail}" download>${T.action_download_thumb}</a>` : ''}
      <button class="btn btn-secondary" id="saveDraftBtn">${T.action_save_draft}</button>
      <button class="btn btn-primary" id="regenerateBtn">${T.action_regenerate}</button>
    </div>
  `;

  document.getElementById('saveDraftBtn').addEventListener('click', (e) => {
    e.target.textContent = T.action_saved_draft;
    e.target.disabled = true;
    if (recentProjects[0]) { recentProjects[0].saved = true; renderRecent(); }
  });
  document.getElementById('regenerateBtn').addEventListener('click', () => {
    if (lastVideoName) runGenerate(lastVideoName);
  });
}

/* ---------- Projetos recentes (só nesta sessão, sem back-end persistente) ---------- */
function renderRecent() {
  if (!recentProjects.length) {
    els.recentContainer.innerHTML = `
      <div class="card empty-state">
        <div class="icon"><svg width="34" height="34" viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.4"/><path d="M8 10h8M8 14h5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg></div>
        <h3>${T.empty_recent_title}</h3>
        <p>${T.empty_recent_body}</p>
      </div>
    `;
    return;
  }
  els.recentContainer.innerHTML = `<div class="recent-grid">${recentProjects.map(p => `
    <div class="card recent-card">
      <img class="thumb" src="${p.thumbnail || ''}" onerror="this.style.visibility='hidden'">
      <div class="meta">
        <span class="name">${p.video_name || ''}</span>
        ${p.saved ? '<span class="badge badge-tag">★</span>' : ''}
      </div>
    </div>
  `).join('')}</div>`;
}
renderRecent();

/* ---------- Botão principal ---------- */
/* ---------- Revisão manual (analisar sem renderizar, ajustar, renderizar sob demanda) ---------- */
let reviewCandidates = [];
let reviewAnalysisPath = null;
let reviewVideoUrl = null;
let reviewSelectedIdx = 0;
let reviewClipStates = {};
let reviewSelectionAnchor = null;

const reviewEls = {
  candidateList: document.getElementById('reviewCandidateList'),
  video: document.getElementById('reviewPreviewVideo'),
  trimStartInput: document.getElementById('trimStartInput'),
  trimEndInput: document.getElementById('trimEndInput'),
  transcriptPanel: document.getElementById('transcriptPanel'),
  panel: document.getElementById('reviewPanel'),
  resultBox: document.getElementById('reviewResultBox'),
};

function defaultReviewState(candidate) {
  return {
    start: candidate.context_start_seconds, end: candidate.end_seconds, title: '',
    orientation: 'vertical', platform: 'sem_preferencia', preset: 'impact', layout: 'gameplay_full',
    subtitleStyle: 'classic', burnCaptions: true, renderedSnapshot: null, result: null,
  };
}

function getReviewState(idx) {
  const c = reviewCandidates[idx];
  if (!reviewClipStates[c.clip_id]) reviewClipStates[c.clip_id] = defaultReviewState(c);
  return reviewClipStates[c.clip_id];
}

function snapshotKey(state) {
  return JSON.stringify({
    start: Math.round(state.start * 10), end: Math.round(state.end * 10),
    orientation: state.orientation, platform: state.platform, preset: state.preset,
    layout: state.layout, subtitleStyle: state.subtitleStyle, burnCaptions: state.burnCaptions,
  });
}

async function startAnalyze(videoName) {
  lastVideoName = videoName;
  setView('processing');
  renderSteps('prepared');
  try {
    const res = await fetch('/api/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_name: videoName }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || T.generate_error_fallback);
    pollAnalyzeJob(data.job_id);
  } catch (e) {
    showToast(e.message, 'error');
    setView('home');
  }
}

function pollAnalyzeJob(jobId) {
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/analyze-status/${jobId}`);
      const data = await res.json();
      if (data.status === 'running') { renderSteps(serverStepToBucket(data.step, data.status)); return; }
      clearInterval(pollTimer);
      if (data.status === 'error') { showToast(data.error || T.processing_failed, 'error'); setView('home'); return; }
      renderSteps('analyzed');
      setTimeout(() => showReview(data), 300);
    } catch (e) {
      clearInterval(pollTimer);
      showToast(T.connection_lost, 'error');
      setView('home');
    }
  }, 2000);
}

function showReview(data) {
  reviewCandidates = data.candidates || [];
  reviewAnalysisPath = data.analysis_path;
  reviewVideoUrl = data.video_url;
  reviewClipStates = {};
  reviewSelectedIdx = 0;

  if (!reviewCandidates.length) {
    showToast(T.review_no_candidates, 'error');
    setView('home');
    return;
  }

  reviewEls.video.src = reviewVideoUrl;
  renderReviewCandidateList();
  selectReviewCandidate(0);
  setView('review');
}

function renderReviewCandidateList() {
  reviewEls.candidateList.innerHTML = reviewCandidates.map((c, idx) => `
    <div class="review-candidate-item ${idx === reviewSelectedIdx ? 'selected' : ''}" data-idx="${idx}">
      <div style="flex:1; min-width:0;">
        <span class="badge badge-score">${Math.round(c.score)}</span>
        <div class="excerpt">${(c.transcript_excerpt || '').slice(0, 90)}</div>
      </div>
    </div>
  `).join('');
  reviewEls.candidateList.querySelectorAll('.review-candidate-item').forEach(item => {
    item.addEventListener('click', () => selectReviewCandidate(parseInt(item.dataset.idx, 10)));
  });
}

function selectReviewCandidate(idx) {
  reviewSelectedIdx = idx;
  reviewSelectionAnchor = null;
  reviewEls.candidateList.querySelectorAll('.review-candidate-item').forEach((item, i) => {
    item.classList.toggle('selected', i === idx);
  });
  const candidate = reviewCandidates[idx];
  const state = getReviewState(idx);
  reviewEls.video.currentTime = state.start;
  updateTrimInputs(state);
  renderTranscriptPanel(candidate, state);
  renderReviewPanel(candidate, state);
}

function updateTrimInputs(state) {
  reviewEls.trimStartInput.value = state.start.toFixed(1);
  reviewEls.trimEndInput.value = state.end.toFixed(1);
}

function renderTranscriptPanel(candidate, state) {
  document.getElementById('transcriptHint').textContent = T.transcript_hint;
  reviewEls.transcriptPanel.innerHTML = (candidate.phrases || []).map((p, i) => {
    const selected = p.start >= state.start - 0.05 && p.end <= state.end + 0.05;
    return `<div class="phrase-row ${selected ? 'selected' : ''}" data-idx="${i}"><span class="ts">${formatDuration(p.start)}</span><span>${p.text}</span></div>`;
  }).join('');

  reviewEls.transcriptPanel.querySelectorAll('.phrase-row').forEach(row => {
    row.addEventListener('click', (e) => {
      const idx = parseInt(row.dataset.idx, 10);
      const phrase = candidate.phrases[idx];
      if (e.shiftKey && reviewSelectionAnchor !== null) {
        const lo = Math.min(reviewSelectionAnchor, idx);
        const hi = Math.max(reviewSelectionAnchor, idx);
        const group = candidate.phrases.slice(lo, hi + 1);
        state.start = Math.min(...group.map(p => p.start));
        state.end = Math.max(...group.map(p => p.end));
        updateTrimInputs(state);
        renderTranscriptPanel(candidate, state);
        renderReviewPanel(candidate, state);
      } else {
        reviewSelectionAnchor = idx;
        reviewEls.video.currentTime = phrase.start;
        reviewEls.video.play().catch(() => {});
      }
    });
  });
}

document.querySelectorAll('.btn-trim').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!reviewCandidates.length) return;
    const state = getReviewState(reviewSelectedIdx);
    const delta = parseFloat(btn.dataset.delta);
    if (btn.dataset.target === 'start') state.start = Math.max(0, Math.round((state.start + delta) * 10) / 10);
    else state.end = Math.max(state.start + 1, Math.round((state.end + delta) * 10) / 10);
    updateTrimInputs(state);
    renderTranscriptPanel(reviewCandidates[reviewSelectedIdx], state);
    renderReviewPanel(reviewCandidates[reviewSelectedIdx], state);
  });
});

[reviewEls.trimStartInput, reviewEls.trimEndInput].forEach(input => {
  input.addEventListener('change', () => {
    if (!reviewCandidates.length) return;
    const state = getReviewState(reviewSelectedIdx);
    const startVal = parseFloat(reviewEls.trimStartInput.value);
    const endVal = parseFloat(reviewEls.trimEndInput.value);
    if (!isNaN(startVal)) state.start = Math.max(0, startVal);
    if (!isNaN(endVal)) state.end = Math.max(state.start + 1, endVal);
    updateTrimInputs(state);
    renderTranscriptPanel(reviewCandidates[reviewSelectedIdx], state);
    renderReviewPanel(reviewCandidates[reviewSelectedIdx], state);
  });
});

function renderReviewPanel(candidate, state) {
  const dirty = state.renderedSnapshot !== snapshotKey(state);
  const dirtyBanner = (dirty && state.renderedSnapshot !== null) ? `<div class="dirty-banner">⚠ ${T.dirty_banner}</div>` : '';

  reviewEls.panel.innerHTML = `
    <div class="panel-group">
      <span class="field-label">${T.panel_title}</span>
      <input type="text" id="reviewTitleInput" placeholder="${T.panel_title_placeholder}" value="${state.title}">
    </div>
    <div class="panel-group">
      <span class="field-label">${T.label_format}</span>
      <div class="tabs" id="reviewOrientationTabs">
        <div class="tab ${state.orientation === 'vertical' ? 'active' : ''}" data-value="vertical">${T.format_vertical}</div>
        <div class="tab ${state.orientation === 'horizontal' ? 'active' : ''}" data-value="horizontal">${T.format_horizontal}</div>
      </div>
    </div>
    <div class="panel-group">
      <span class="field-label">${T.label_platform}</span>
      <div class="tabs" id="reviewPlatformTabs">
        ${['sem_preferencia', 'tiktok', 'reels', 'shorts'].map(p => `<div class="tab ${state.platform === p ? 'active' : ''}" data-value="${p}">${p === 'sem_preferencia' ? T.platform_none : p}</div>`).join('')}
      </div>
    </div>
    <div class="panel-group">
      <span class="field-label">${T.label_preset}</span>
    </div>
    <div class="panel-group">
      <span class="field-label">${T.label_layout}</span>
      <div class="tabs" id="reviewLayoutTabs" style="flex-wrap:wrap;">
        <div class="tab ${state.layout === 'gameplay_full' ? 'active' : ''}" data-value="gameplay_full">${T.layout_gameplay_full}</div>
        <div class="tab ${state.layout === 'gameplay_facecam' ? 'active' : ''}" data-value="gameplay_facecam">${T.layout_gameplay_facecam}</div>
        <div class="tab ${state.layout === 'facecam_focus' ? 'active' : ''}" data-value="facecam_focus">${T.layout_facecam_focus}</div>
        <div class="tab ${state.layout === 'blur_background' ? 'active' : ''}" data-value="blur_background">${T.layout_blur_background}</div>
      </div>
    </div>
    <div class="panel-group">
      <span class="field-label">${T.label_subtitle_style}</span>
      <select id="reviewSubtitleSelect">
        <option value="classic" ${state.subtitleStyle === 'classic' ? 'selected' : ''}>${T.style_classic}</option>
        <option value="bold_yellow" ${state.subtitleStyle === 'bold_yellow' ? 'selected' : ''}>${T.style_bold_yellow}</option>
        <option value="minimal_top" ${state.subtitleStyle === 'minimal_top' ? 'selected' : ''}>${T.style_minimal_top}</option>
        <option value="boxed" ${state.subtitleStyle === 'boxed' ? 'selected' : ''}>${T.style_boxed}</option>
      </select>
      <div class="checkbox-row" style="margin-top:8px;">
        <input type="checkbox" id="reviewCaptionsCheckbox" ${state.burnCaptions ? 'checked' : ''}>
        <label for="reviewCaptionsCheckbox">${T.label_captions}</label>
      </div>
    </div>
    ${dirtyBanner}
    <button class="btn btn-primary" id="reviewRenderBtn" style="width:100%;">${T.review_render_btn}</button>
  `;

  document.getElementById('reviewTitleInput').addEventListener('input', (e) => { state.title = e.target.value; });
  setupTabs(document.getElementById('reviewOrientationTabs'), v => { state.orientation = v; renderReviewPanel(candidate, state); });
  setupTabs(document.getElementById('reviewPlatformTabs'), v => { state.platform = v; renderReviewPanel(candidate, state); });
  setupTabs(document.getElementById('reviewLayoutTabs'), v => { state.layout = v; renderReviewPanel(candidate, state); });
  document.getElementById('reviewSubtitleSelect').addEventListener('change', (e) => { state.subtitleStyle = e.target.value; renderReviewPanel(candidate, state); });
  document.getElementById('reviewCaptionsCheckbox').addEventListener('change', (e) => { state.burnCaptions = e.target.checked; renderReviewPanel(candidate, state); });
  document.getElementById('reviewRenderBtn').addEventListener('click', () => renderReviewClip(candidate, state));

  renderReviewResultBox(state);
}

function renderReviewResultBox(state) {
  if (!state.result) { reviewEls.resultBox.style.display = 'none'; reviewEls.resultBox.innerHTML = ''; return; }
  reviewEls.resultBox.style.display = 'block';
  reviewEls.resultBox.innerHTML = `
    <video src="${state.result.video}" controls></video>
    <a class="btn btn-secondary" style="width:100%; max-width:220px; display:flex; margin:0 auto;" href="${state.result.video}" download>${T.review_download}</a>
  `;
}

async function renderReviewClip(candidate, state) {
  const btn = document.getElementById('reviewRenderBtn');
  btn.disabled = true;
  btn.textContent = T.review_rendering;
  try {
    const res = await fetch('/api/render-clip', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        analysis_path: reviewAnalysisPath, clip_id: candidate.clip_id,
        start_seconds: state.start, end_seconds: state.end,
        orientation: state.orientation, burn_captions: state.burnCaptions,
        subtitle_style: state.subtitleStyle, preset: state.preset, layout: state.layout,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || T.generate_error_fallback);
    state.result = data;
    state.renderedSnapshot = snapshotKey(state);
    showToast(T.toast_generated, 'success');
    renderReviewPanel(candidate, state);
  } catch (e) {
    showToast(e.message, 'error');
    btn.disabled = false;
    btn.textContent = T.review_render_btn;
  }
}

document.getElementById('backToHomeFromReviewBtn').addEventListener('click', () => setView('home'));

els.generateBtn.addEventListener('click', () => {
  const videoName = els.videoSelect.value || lastVideoName;
  if (!videoName) { showToast(T.dropzone_title, 'error'); return; }
  if (selectedMode === 'review') {
    startAnalyze(videoName);
  } else {
    runGenerate(videoName);
  }
});

loadVideos();
