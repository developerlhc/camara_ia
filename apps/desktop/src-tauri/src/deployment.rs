use rand::{distr::Alphanumeric, Rng};
use reqwest::{Client, Method};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    env, fs,
    path::{Path, PathBuf},
    process::{Command as StdCommand, Stdio},
};
use tauri::{Manager, State};
use tauri_plugin_opener::OpenerExt;
use tokio::{
    io::{AsyncBufReadExt, BufReader},
    process::{Child, Command},
    sync::Mutex,
    task::JoinHandle,
    time::{sleep, timeout, Duration, Instant},
};

#[derive(Clone)]
struct Session {
    origin: String,
    csrf: String,
    client: Client,
    user: Value,
}

pub struct Operations {
    session: Mutex<Option<Session>>,
    recorder: Mutex<Option<Child>>,
    tunnel: Mutex<Option<Child>>,
    heartbeat: Mutex<Option<JoinHandle<()>>>,
    recording_site: Mutex<Option<String>>,
}

impl Default for Operations {
    fn default() -> Self {
        Self {
            session: Mutex::new(None),
            recorder: Mutex::new(None),
            tunnel: Mutex::new(None),
            heartbeat: Mutex::new(None),
            recording_site: Mutex::new(None),
        }
    }
}

#[derive(Deserialize)]
pub struct LoginSettings {
    pub web_origin: String,
    pub identifier: String,
    pub password: String,
}

#[derive(Clone, Deserialize, Serialize)]
pub struct RecordingCamera {
    pub id: String,
    pub name: String,
    pub source: String,
    pub fps: f64,
    pub enabled: bool,
}

#[derive(Clone, Deserialize, Serialize)]
pub struct RecorderSettings {
    #[serde(default)]
    pub site_id: Option<String>,
    pub output_dir: String,
    pub retention_days: u16,
    pub min_free_gb: f64,
    pub detector: String,
    pub confidence: f64,
    pub model: String,
    #[serde(default = "default_gateway_port")]
    pub gateway_port: u16,
    #[serde(default)]
    pub gateway_token: String,
    #[serde(default)]
    pub cameras: Vec<RecordingCamera>,
}

fn default_gateway_port() -> u16 {
    8788
}

#[derive(Deserialize)]
pub struct RecordingCameraInput {
    pub site_id: String,
    pub id: String,
    pub name: String,
    pub source: String,
    pub fps: Option<f64>,
}

fn public_origin(value: &str) -> Result<String, String> {
    let url = url::Url::parse(value).map_err(|_| "Dirección HTTPS inválida")?;
    let local = matches!(url.host_str(), Some("localhost" | "127.0.0.1"));
    if (url.scheme() != "https" && !(local && url.scheme() == "http"))
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/"
    {
        return Err("Usa la dirección de Vigilay sin rutas ni credenciales".into());
    }
    Ok(url.origin().ascii_serialization())
}

fn api_error(status: reqwest::StatusCode, value: &Value) -> String {
    value
        .get("detail")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .unwrap_or_else(|| format!("Vigilay respondió con estado {status}"))
}

fn stream_agent_script() -> Result<(PathBuf, PathBuf), String> {
    let mut roots = Vec::new();
    if let Some(root) = env::var_os("VIGILAY_PROJECT_ROOT") {
        roots.push(PathBuf::from(root));
    }
    roots.push(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join(".."),
    );
    if let Ok(root) = env::current_dir() {
        roots.push(root);
    }
    for root in roots {
        let script = root.join("scripts").join("asegurar-agente-stream.ps1");
        if script.is_file() {
            let root = root
                .canonicalize()
                .map_err(|_| "No se pudo validar la instalación local de Vigilay")?;
            return Ok((root, script));
        }
    }
    Err("Este instalador no encontró el agente local de video de Vigilay".into())
}

#[tauri::command]
pub fn ensure_stream_agent() -> Result<Value, String> {
    let (root, script) = stream_agent_script()?;
    let mut command = StdCommand::new("powershell.exe");
    command
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ])
        .arg(script)
        .current_dir(root)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let status = command
        .status()
        .map_err(|_| "Vigilay Desktop no pudo iniciar el agente local de video")?;
    if !status.success() {
        return Err("El agente local de video no confirmó su inicio".into());
    }
    Ok(json!({"managed": true}))
}

async fn request(
    session: &Session,
    method: Method,
    path: &str,
    body: Option<Value>,
) -> Result<Value, String> {
    let mut call = session
        .client
        .request(method.clone(), format!("{}{}", session.origin, path));
    if method != Method::GET {
        call = call
            .header("Origin", &session.origin)
            .header("x-csrf-token", &session.csrf);
    }
    if let Some(value) = body {
        call = call.json(&value);
    }
    let response = call
        .send()
        .await
        .map_err(|_| "No se pudo conectar con Vigilay Web")?;
    let status = response.status();
    let bytes = response
        .bytes()
        .await
        .map_err(|_| "Respuesta incompleta de Vigilay")?;
    let value = if bytes.is_empty() {
        json!({"ok": true})
    } else {
        serde_json::from_slice(&bytes).map_err(|_| "Vigilay devolvió una respuesta inválida")?
    };
    if !status.is_success() {
        return Err(api_error(status, &value));
    }
    Ok(value)
}

fn recorder_config_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|path| path.join("recorder.json"))
        .map_err(|_| "No se pudo obtener el directorio privado de Vigilay".into())
}

fn default_recorder_settings(app: &tauri::AppHandle) -> Result<RecorderSettings, String> {
    let output = app
        .path()
        .video_dir()
        .or_else(|_| app.path().app_data_dir())
        .map_err(|_| "No se pudo obtener una carpeta de grabación".to_string())?
        .join("Vigilay");
    let gateway_token: String = rand::rng()
        .sample_iter(&Alphanumeric)
        .take(64)
        .map(char::from)
        .collect();
    Ok(RecorderSettings {
        site_id: None,
        output_dir: output.to_string_lossy().into_owned(),
        retention_days: 7,
        min_free_gb: 2.0,
        detector: "yolo".into(),
        confidence: 0.45,
        model: "yolo11n.pt".into(),
        gateway_port: default_gateway_port(),
        gateway_token,
        cameras: Vec::new(),
    })
}

fn read_recorder_settings(app: &tauri::AppHandle) -> Result<RecorderSettings, String> {
    let path = recorder_config_path(app)?;
    if !path.exists() {
        return default_recorder_settings(app);
    }
    let bytes = fs::read(path).map_err(|_| "No se pudo leer la configuración del grabador")?;
    serde_json::from_slice(&bytes)
        .map_err(|_| "La configuración local del grabador está dañada".into())
}

fn validate_video_source(value: &str) -> Result<(), String> {
    let parsed = url::Url::parse(value).map_err(|_| "La fuente de video no es válida")?;
    if !matches!(parsed.scheme(), "rtsp" | "rtsps" | "http" | "https")
        || parsed.host_str().is_none()
        || parsed.fragment().is_some()
        || value.len() > 2048
        || value.chars().any(|character| character.is_control())
    {
        return Err("La fuente debe ser una URL RTSP o HTTP válida".into());
    }
    Ok(())
}

fn validate_recorder_settings(mut value: RecorderSettings) -> Result<RecorderSettings, String> {
    if value
        .site_id
        .as_ref()
        .is_some_and(|site_id| site_id.len() != 36)
    {
        return Err("La sede guardada para el grabador no es válida".into());
    }
    if !(1..=365).contains(&value.retention_days) {
        return Err("La retención debe estar entre 1 y 365 días".into());
    }
    if !(0.0..=1024.0).contains(&value.min_free_gb) {
        return Err("La reserva de espacio no es válida".into());
    }
    if !matches!(value.detector.as_str(), "motion" | "yolo") {
        return Err("Selecciona un detector válido".into());
    }
    if !(0.1..=0.95).contains(&value.confidence) {
        return Err("La confianza debe estar entre 0.1 y 0.95".into());
    }
    if value.gateway_port < 1024 || value.gateway_token.len() < 32 {
        return Err("La credencial o el puerto del servicio local no son válidos".into());
    }
    let output = PathBuf::from(value.output_dir.trim());
    if output.as_os_str().is_empty() || !output.is_absolute() {
        return Err("Selecciona una ruta absoluta para las grabaciones".into());
    }
    fs::create_dir_all(&output).map_err(|_| "No se pudo crear la carpeta de grabaciones")?;
    let output = output
        .canonicalize()
        .map_err(|_| "No se pudo validar la carpeta de grabaciones")?;
    let probe = output.join(".vigilay-write-test");
    fs::write(&probe, b"vigilay").map_err(|_| "Vigilay no puede escribir en esa carpeta")?;
    fs::remove_file(probe).map_err(|_| "No se pudo completar la prueba de escritura")?;
    value.output_dir = output.to_string_lossy().into_owned();
    let mut ids = HashSet::new();
    for camera in &value.cameras {
        if camera.id.is_empty()
            || camera.id.len() > 80
            || !camera
                .id
                .chars()
                .all(|character| character.is_ascii_alphanumeric() || "-_".contains(character))
            || !ids.insert(&camera.id)
        {
            return Err("Hay un identificador de cámara local inválido o duplicado".into());
        }
        validate_video_source(&camera.source)?;
        if !(1.0..=30.0).contains(&camera.fps) {
            return Err("Los FPS deben estar entre 1 y 30".into());
        }
    }
    Ok(value)
}

fn write_recorder_settings(
    app: &tauri::AppHandle,
    value: RecorderSettings,
) -> Result<RecorderSettings, String> {
    let value = validate_recorder_settings(value)?;
    let path = recorder_config_path(app)?;
    let parent = path
        .parent()
        .ok_or("No se pudo preparar el directorio privado")?;
    fs::create_dir_all(parent).map_err(|_| "No se pudo preparar el directorio privado")?;
    let pending = path.with_extension("pending");
    let bytes =
        serde_json::to_vec_pretty(&value).map_err(|_| "No se pudo serializar la configuración")?;
    fs::write(&pending, bytes).map_err(|_| "No se pudo guardar la configuración del grabador")?;
    fs::copy(&pending, &path).map_err(|_| "No se pudo activar la configuración del grabador")?;
    fs::remove_file(pending).map_err(|_| "No se pudo finalizar la configuración del grabador")?;
    Ok(value)
}

fn recorder_command(config: &Path) -> Result<Command, String> {
    if let Ok(executable) = env::var("VIGILAY_RECORDER_EXECUTABLE") {
        let path = PathBuf::from(executable);
        if path.is_file() {
            let mut command = Command::new(path);
            command.arg("--config").arg(config);
            return Ok(command);
        }
    }
    if let Ok(current) = env::current_exe() {
        if let Some(parent) = current.parent() {
            let bundled = parent.join("vigilay-recorder.exe");
            if bundled.is_file() {
                let mut command = Command::new(bundled);
                command.arg("--config").arg(config);
                return Ok(command);
            }
        }
    }
    let mut starts = Vec::new();
    if let Ok(path) = env::current_exe() {
        starts.push(path);
    }
    if let Ok(path) = env::current_dir() {
        starts.push(path);
    }
    for start in starts {
        for ancestor in start.ancestors() {
            let python = ancestor.join(".venv").join("Scripts").join("python.exe");
            let agent = ancestor
                .join("tools")
                .join("vigilay_recorder")
                .join("agent.py");
            if python.is_file() && agent.is_file() {
                let mut command = Command::new(python);
                command
                    .current_dir(ancestor)
                    .args(["-m", "tools.vigilay_recorder.agent", "--config"])
                    .arg(config);
                return Ok(command);
            }
        }
    }
    Err("No se encontró el motor local de grabación. Instala Vigilay Recorder".into())
}

async fn wait_for_recorder(child: &mut Child, port: u16, token: &str) -> Result<(), String> {
    let endpoint = format!("http://127.0.0.1:{port}/api/cameras");
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .map_err(|_| "No se pudo preparar la comprobación del grabador")?;
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        if child
            .try_wait()
            .map_err(|_| "No se pudo comprobar Vigilay Recorder")?
            .is_some()
        {
            return Err(
                "Vigilay Recorder terminó durante el inicio; revisa su configuración".into(),
            );
        }
        if let Ok(response) = client.get(&endpoint).bearer_auth(token).send().await {
            if response.status().is_success() {
                return Ok(());
            }
        }
        if Instant::now() >= deadline {
            return Err("Vigilay Recorder no respondió durante el inicio".into());
        }
        sleep(Duration::from_millis(400)).await;
    }
}

fn tunnel_url(line: &str) -> Option<String> {
    let start = line.find("https://")?;
    let candidate = line[start..]
        .split_whitespace()
        .next()?
        .trim_matches(|character: char| {
            !character.is_ascii_alphanumeric() && !":/.-".contains(character)
        });
    let parsed = url::Url::parse(candidate).ok()?;
    let host = parsed.host_str()?;
    if parsed.scheme() == "https" && host.ends_with(".trycloudflare.com") {
        Some(parsed.origin().ascii_serialization())
    } else {
        None
    }
}

async fn start_tunnel(port: u16) -> Result<(Child, String), String> {
    let executable = env::var("CLOUDFLARED_PATH").unwrap_or_else(|_| "cloudflared".into());
    let mut command = Command::new(executable);
    command
        .args([
            "tunnel",
            "--no-autoupdate",
            "--url",
            &format!("http://127.0.0.1:{port}"),
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let mut child = command.spawn().map_err(|_| {
        "No se encontró cloudflared. Instálalo o configura CLOUDFLARED_PATH para publicar la sede"
    })?;
    let stderr = child
        .stderr
        .take()
        .ok_or("No se pudo leer el inicio del túnel")?;
    let discovered = timeout(Duration::from_secs(45), async {
        let mut lines = BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if let Some(endpoint) = tunnel_url(&line) {
                return Some(endpoint);
            }
        }
        None
    })
    .await
    .map_err(|_| "Cloudflare no publicó la sede en 45 segundos")?
    .ok_or("Cloudflare terminó sin publicar una dirección")?;
    Ok((child, discovered))
}

async fn publish_recorder_connection(
    session: &Session,
    site_id: &str,
    endpoint_url: &str,
    gateway_token: &str,
    status: &str,
) -> Result<Value, String> {
    request(
        session,
        Method::PUT,
        "/api/v1/media/connection",
        Some(json!({
            "site_id": site_id,
            "endpoint_url": endpoint_url,
            "gateway_token": gateway_token,
            "status": status,
        })),
    )
    .await
}

async fn heartbeat_recorder_connection(
    session: &Session,
    site_id: &str,
    endpoint_url: &str,
    gateway_token: &str,
    status: &str,
) -> Result<Value, String> {
    request(
        session,
        Method::PUT,
        "/api/v1/media/connection/heartbeat",
        Some(json!({
            "site_id": site_id,
            "endpoint_url": endpoint_url,
            "gateway_token": gateway_token,
            "status": status,
        })),
    )
    .await
}

#[tauri::command]
pub async fn login(state: State<'_, Operations>, settings: LoginSettings) -> Result<Value, String> {
    let origin = public_origin(&settings.web_origin)?;
    if settings.identifier.trim().is_empty() || settings.password.is_empty() {
        return Err("Escribe tu usuario y contraseña de Vigilay".into());
    }
    let client = Client::builder()
        .cookie_store(true)
        .timeout(std::time::Duration::from_secs(20))
        .user_agent("Vigilay-Desktop/0.3")
        .build()
        .map_err(|_| "No se pudo preparar la conexión segura")?;
    let response = client
        .post(format!("{origin}/api/v1/auth/login"))
        .header("Origin", &origin)
        .json(&json!({"identifier": settings.identifier, "password": settings.password}))
        .send()
        .await
        .map_err(|_| "No se pudo conectar con Vigilay Web")?;
    let status = response.status();
    let value: Value = response
        .json()
        .await
        .map_err(|_| "Vigilay devolvió una respuesta inválida")?;
    if !status.is_success() {
        return Err(api_error(status, &value));
    }
    let csrf = value
        .get("csrf_token")
        .and_then(Value::as_str)
        .ok_or("La sesión no incluyó protección CSRF")?
        .to_owned();
    let user = value
        .get("user")
        .cloned()
        .ok_or("La sesión no incluyó el usuario")?;
    *state.session.lock().await = Some(Session {
        origin,
        csrf,
        client,
        user: user.clone(),
    });
    Ok(json!({"user": user, "connected": true}))
}

#[tauri::command]
pub async fn logout(state: State<'_, Operations>) -> Result<Value, String> {
    let mut guard = state.session.lock().await;
    if let Some(session) = guard.as_ref() {
        request(session, Method::POST, "/api/v1/auth/logout", None).await?;
    }
    *guard = None;
    Ok(json!({"connected": false}))
}

#[tauri::command]
pub async fn catalog(state: State<'_, Operations>) -> Result<Value, String> {
    let guard = state.session.lock().await;
    let session = guard.as_ref().ok_or("Primero inicia sesión")?;
    let tenants = request(session, Method::GET, "/api/v1/tenants?limit=200", None).await?;
    let sites = request(session, Method::GET, "/api/v1/sites?limit=200", None).await?;
    Ok(json!({"tenants": tenants, "sites": sites, "user": session.user}))
}

#[tauri::command]
pub async fn create_tenant(state: State<'_, Operations>, data: Value) -> Result<Value, String> {
    let guard = state.session.lock().await;
    let session = guard.as_ref().ok_or("Primero inicia sesión")?;
    request(
        session,
        Method::POST,
        "/api/v1/tenants",
        Some(json!({"name": data.get("name"), "legal_name": "", "tax_id": "", "timezone": "America/Lima"})),
    )
    .await
}

#[tauri::command]
pub async fn create_site(state: State<'_, Operations>, data: Value) -> Result<Value, String> {
    let guard = state.session.lock().await;
    let session = guard.as_ref().ok_or("Primero inicia sesión")?;
    request(
        session,
        Method::POST,
        "/api/v1/sites",
        Some(json!({"tenant_id": data.get("tenant_id"), "name": data.get("name"), "address": data.get("address").and_then(Value::as_str).unwrap_or(""), "description": ""})),
    )
    .await
}

#[tauri::command]
pub async fn cameras(
    state: State<'_, Operations>,
    tenant_id: String,
    site_id: String,
) -> Result<Value, String> {
    let guard = state.session.lock().await;
    let session = guard.as_ref().ok_or("Primero inicia sesión")?;
    request(
        session,
        Method::GET,
        &format!("/api/v1/cameras?limit=200&tenant_id={tenant_id}&site_id={site_id}"),
        None,
    )
    .await
}

#[tauri::command]
pub async fn start_live(state: State<'_, Operations>, camera_id: String) -> Result<Value, String> {
    if camera_id.len() != 36 {
        return Err("Selecciona una cámara válida".into());
    }
    let guard = state.session.lock().await;
    let session = guard.as_ref().ok_or("Primero inicia sesión")?;
    request(
        session,
        Method::POST,
        &format!("/api/v1/cameras/{camera_id}/live/start"),
        None,
    )
    .await
}

#[tauri::command]
pub async fn heartbeat_live(
    state: State<'_, Operations>,
    camera_id: String,
    session_id: String,
    viewer_key: String,
) -> Result<Value, String> {
    let guard = state.session.lock().await;
    let session = guard.as_ref().ok_or("Primero inicia sesión")?;
    request(
        session,
        Method::POST,
        &format!("/api/v1/cameras/{camera_id}/live/heartbeat"),
        Some(json!({"session_id": session_id, "viewer_key": viewer_key})),
    )
    .await
}

#[tauri::command]
pub async fn stop_live(
    state: State<'_, Operations>,
    camera_id: String,
    session_id: String,
    viewer_key: String,
) -> Result<Value, String> {
    let guard = state.session.lock().await;
    let session = guard.as_ref().ok_or("Primero inicia sesión")?;
    request(
        session,
        Method::POST,
        &format!("/api/v1/cameras/{camera_id}/live/stop"),
        Some(json!({"session_id": session_id, "viewer_key": viewer_key})),
    )
    .await
}

#[tauri::command]
pub async fn create_camera(state: State<'_, Operations>, data: Value) -> Result<Value, String> {
    let guard = state.session.lock().await;
    let session = guard.as_ref().ok_or("Primero inicia sesión")?;
    let brand = data
        .get("brand")
        .and_then(Value::as_str)
        .unwrap_or("GENERIC");
    request(
        session,
        Method::POST,
        "/api/v1/cameras",
        Some(json!({
            "tenant_id": data.get("tenant_id"), "site_id": data.get("site_id"),
            "name": data.get("name"), "integration_type": if brand == "V380" { "V380" } else { "RTSP" },
            "brand": brand, "model": data.get("model").and_then(Value::as_str).unwrap_or(""),
            "target_fps": 15, "grayscale": false, "rtsp_url": data.get("rtsp_url")
        })),
    )
    .await
}

#[tauri::command]
pub fn recorder_settings(app: tauri::AppHandle) -> Result<Value, String> {
    let value = read_recorder_settings(&app)?;
    Ok(json!({
        "site_id": value.site_id,
        "output_dir": value.output_dir, "retention_days": value.retention_days,
        "min_free_gb": value.min_free_gb, "detector": value.detector,
        "confidence": value.confidence, "camera_count": value.cameras.len()
    }))
}

#[tauri::command]
pub fn choose_recording_directory() -> Result<Option<String>, String> {
    Ok(rfd::FileDialog::new()
        .set_title("Carpeta de grabaciones Vigilay")
        .pick_folder()
        .map(|path| path.to_string_lossy().into_owned()))
}

#[tauri::command]
pub async fn save_recorder_settings(
    app: tauri::AppHandle,
    state: State<'_, Operations>,
    data: Value,
) -> Result<Value, String> {
    let mut process = state.recorder.lock().await;
    if let Some(child) = process.as_mut() {
        if child
            .try_wait()
            .map_err(|_| "No se pudo consultar el grabador")?
            .is_none()
        {
            return Err("Detén la grabación antes de cambiar su configuración".into());
        }
    }
    *process = None;
    drop(process);
    let mut current = read_recorder_settings(&app)?;
    current.output_dir = data
        .get("output_dir")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    current.retention_days = data
        .get("retention_days")
        .and_then(Value::as_u64)
        .unwrap_or(7) as u16;
    current.min_free_gb = data
        .get("min_free_gb")
        .and_then(Value::as_f64)
        .unwrap_or(2.0);
    current.detector = data
        .get("detector")
        .and_then(Value::as_str)
        .unwrap_or("yolo")
        .to_owned();
    current.confidence = data
        .get("confidence")
        .and_then(Value::as_f64)
        .unwrap_or(0.45);
    let saved = write_recorder_settings(&app, current)?;
    Ok(json!({"saved": true, "output_dir": saved.output_dir, "camera_count": saved.cameras.len()}))
}

#[tauri::command]
pub async fn register_recording_camera(
    app: tauri::AppHandle,
    state: State<'_, Operations>,
    data: RecordingCameraInput,
) -> Result<Value, String> {
    if data.site_id.len() != 36 {
        return Err("Selecciona la sede de la cámara".into());
    }
    let mut process = state.recorder.lock().await;
    if let Some(child) = process.as_mut() {
        if child
            .try_wait()
            .map_err(|_| "No se pudo consultar el grabador")?
            .is_none()
        {
            return Err("Detén la grabación antes de agregar otra cámara".into());
        }
    }
    *process = None;
    drop(process);
    validate_video_source(&data.source)?;
    let mut settings = read_recorder_settings(&app)?;
    if settings.site_id.as_deref() != Some(data.site_id.as_str()) {
        settings.cameras.clear();
        settings.site_id = Some(data.site_id.clone());
    }
    settings.cameras.retain(|camera| camera.id != data.id);
    settings.cameras.push(RecordingCamera {
        id: data.id,
        name: data.name,
        source: data.source,
        fps: data.fps.unwrap_or(15.0),
        enabled: true,
    });
    let count = write_recorder_settings(&app, settings)?.cameras.len();
    Ok(json!({"registered": true, "camera_count": count}))
}

#[tauri::command]
pub async fn sync_recording_cameras(
    app: tauri::AppHandle,
    state: State<'_, Operations>,
    site_id: String,
) -> Result<Value, String> {
    if site_id.len() != 36 {
        return Err("Selecciona la sede que se sincronizará".into());
    }
    let mut process = state.recorder.lock().await;
    if let Some(child) = process.as_mut() {
        if child
            .try_wait()
            .map_err(|_| "No se pudo consultar el grabador")?
            .is_none()
        {
            return Err("Detén la grabación antes de sincronizar cámaras".into());
        }
    }
    *process = None;
    drop(process);

    let response = {
        let guard = state.session.lock().await;
        let session = guard.as_ref().ok_or("Primero inicia sesión")?;
        request(
            session,
            Method::POST,
            &format!("/api/v1/sites/{site_id}/recorder-cameras"),
            Some(json!({})),
        )
        .await?
    };
    let returned_site = response
        .get("site_id")
        .and_then(Value::as_str)
        .ok_or("Vigilay no devolvió la sede del grabador")?;
    if returned_site != site_id {
        return Err("Vigilay devolvió cámaras de otra sede".into());
    }
    let cameras: Vec<RecordingCamera> = serde_json::from_value(
        response
            .get("cameras")
            .cloned()
            .ok_or("Vigilay no devolvió las cámaras")?,
    )
    .map_err(|_| "Vigilay devolvió cámaras inválidas")?;
    for camera in &cameras {
        validate_video_source(&camera.source)?;
    }
    let mut settings = read_recorder_settings(&app)?;
    settings.site_id = Some(site_id);
    settings.cameras = cameras;
    let saved = write_recorder_settings(&app, settings)?;
    Ok(json!({
        "synchronized": true,
        "camera_count": saved.cameras.len(),
        "cameras": saved.cameras.iter().map(|camera| camera.name.clone()).collect::<Vec<_>>()
    }))
}

#[tauri::command]
pub async fn start_recorder(
    app: tauri::AppHandle,
    state: State<'_, Operations>,
    site_id: String,
) -> Result<Value, String> {
    if site_id.len() != 36 {
        return Err("Selecciona la sede que almacenará estas grabaciones".into());
    }
    let settings = validate_recorder_settings(read_recorder_settings(&app)?)?;
    if settings.site_id.as_deref() != Some(site_id.as_str()) {
        return Err("Sincroniza las cámaras de la sede seleccionada antes de grabar".into());
    }
    if settings.cameras.iter().all(|camera| !camera.enabled) {
        return Err("Configura al menos una cámara local".into());
    }
    let session = state
        .session
        .lock()
        .await
        .as_ref()
        .cloned()
        .ok_or("Primero inicia sesión")?;
    let mut guard = state.recorder.lock().await;
    if let Some(child) = guard.as_mut() {
        if child
            .try_wait()
            .map_err(|_| "No se pudo consultar el grabador")?
            .is_none()
        {
            let current_site = state.recording_site.lock().await.clone();
            if current_site.as_deref() != Some(site_id.as_str()) {
                return Err("El grabador ya está activo para otra sede".into());
            }
            return Ok(json!({"running": true, "already_running": true}));
        }
    }
    *guard = None;
    drop(guard);
    if let Some(task) = state.heartbeat.lock().await.take() {
        task.abort();
    }
    if let Some(tunnel) = state.tunnel.lock().await.as_mut() {
        let _ = tunnel.kill().await;
    }
    *state.tunnel.lock().await = None;
    let mut guard = state.recorder.lock().await;
    let mut command = recorder_command(&recorder_config_path(&app)?)?;
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let mut child = command
        .spawn()
        .map_err(|_| "No se pudo iniciar Vigilay Recorder")?;
    let pid = child.id();
    if let Err(error) =
        wait_for_recorder(&mut child, settings.gateway_port, &settings.gateway_token).await
    {
        let _ = child.kill().await;
        return Err(error);
    }
    let local_only = env::var("VIGILAY_RECORDER_LOCAL_ONLY")
        .map(|value| value.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    let mut endpoint = format!("http://127.0.0.1:{}", settings.gateway_port);
    if !local_only {
        let (tunnel, public_endpoint) = match start_tunnel(settings.gateway_port).await {
            Ok(value) => value,
            Err(error) => {
                let _ = child.kill().await;
                return Err(error);
            }
        };
        endpoint = public_endpoint;
        *state.tunnel.lock().await = Some(tunnel);
    }
    if let Err(error) = publish_recorder_connection(
        &session,
        &site_id,
        &endpoint,
        &settings.gateway_token,
        "ONLINE",
    )
    .await
    {
        if let Some(tunnel) = state.tunnel.lock().await.as_mut() {
            let _ = tunnel.kill().await;
        }
        *state.tunnel.lock().await = None;
        let _ = child.kill().await;
        return Err(error);
    }
    let heartbeat_session = session.clone();
    let heartbeat_site = site_id.clone();
    let heartbeat_endpoint = endpoint.clone();
    let heartbeat_local_endpoint =
        format!("http://127.0.0.1:{}/api/cameras", settings.gateway_port);
    let heartbeat_token = settings.gateway_token.clone();
    *state.heartbeat.lock().await = Some(tokio::spawn(async move {
        loop {
            sleep(Duration::from_secs(10)).await;
            let local_online = heartbeat_session
                .client
                .get(&heartbeat_local_endpoint)
                .bearer_auth(&heartbeat_token)
                .timeout(std::time::Duration::from_secs(3))
                .send()
                .await
                .map(|response| response.status().is_success())
                .unwrap_or(false);
            let _ = heartbeat_recorder_connection(
                &heartbeat_session,
                &heartbeat_site,
                if local_online {
                    &heartbeat_endpoint
                } else {
                    ""
                },
                &heartbeat_token,
                if local_online { "ONLINE" } else { "OFFLINE" },
            )
            .await;
        }
    }));
    *state.recording_site.lock().await = Some(site_id);
    *guard = Some(child);
    Ok(
        json!({"running": true, "pid": pid, "output_dir": settings.output_dir, "endpoint": endpoint}),
    )
}

#[tauri::command]
pub async fn stop_recorder(
    app: tauri::AppHandle,
    state: State<'_, Operations>,
) -> Result<Value, String> {
    if let Some(task) = state.heartbeat.lock().await.take() {
        task.abort();
    }
    if let Some(tunnel) = state.tunnel.lock().await.as_mut() {
        let _ = tunnel.kill().await;
    }
    *state.tunnel.lock().await = None;
    let mut guard = state.recorder.lock().await;
    if let Some(child) = guard.as_mut() {
        child
            .kill()
            .await
            .map_err(|_| "No se pudo detener Vigilay Recorder")?;
    }
    *guard = None;
    let site_id = state.recording_site.lock().await.take();
    let session = state.session.lock().await.as_ref().cloned();
    if let (Some(site_id), Some(session)) = (site_id, session) {
        let settings = read_recorder_settings(&app)?;
        let _ = heartbeat_recorder_connection(
            &session,
            &site_id,
            "",
            &settings.gateway_token,
            "OFFLINE",
        )
        .await;
    }
    Ok(json!({"running": false}))
}

#[tauri::command]
pub async fn recorder_status(
    app: tauri::AppHandle,
    state: State<'_, Operations>,
) -> Result<Value, String> {
    let settings = read_recorder_settings(&app)?;
    let mut guard = state.recorder.lock().await;
    let running = match guard.as_mut() {
        Some(child) => child
            .try_wait()
            .map_err(|_| "No se pudo consultar el grabador")?
            .is_none(),
        None => false,
    };
    if !running {
        *guard = None;
    }
    Ok(
        json!({"running": running, "output_dir": settings.output_dir, "camera_count": settings.cameras.len()}),
    )
}

#[tauri::command]
pub fn open_recordings(app: tauri::AppHandle) -> Result<(), String> {
    let settings = read_recorder_settings(&app)?;
    fs::create_dir_all(&settings.output_dir).map_err(|_| "No se pudo abrir la carpeta")?;
    app.opener()
        .open_path(settings.output_dir, None::<&str>)
        .map_err(|_| "No se pudo abrir la carpeta de grabaciones".into())
}

#[tauri::command]
pub fn open_web(state: State<'_, Operations>, app: tauri::AppHandle) -> Result<(), String> {
    let guard = state.session.blocking_lock();
    let origin = &guard.as_ref().ok_or("Primero inicia sesión")?.origin;
    app.opener()
        .open_url(origin, None::<&str>)
        .map_err(|_| "No se pudo abrir Vigilay Web".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_public_origin() {
        assert_eq!(
            public_origin("https://vigilay.example/").unwrap(),
            "https://vigilay.example"
        );
        assert!(public_origin("https://user:pass@vigilay.example/").is_err());
        assert!(public_origin("https://vigilay.example/login").is_err());
        assert!(public_origin("http://vigilay.example/").is_err());
        assert!(public_origin("http://localhost:3000/").is_ok());
    }

    #[test]
    fn validates_recording_configuration() {
        let root = env::temp_dir().join(format!("vigilay-recorder-test-{}", std::process::id()));
        let settings = RecorderSettings {
            site_id: None,
            output_dir: root.to_string_lossy().into_owned(),
            retention_days: 7,
            min_free_gb: 1.0,
            detector: "motion".into(),
            confidence: 0.5,
            model: "model.pt".into(),
            gateway_port: default_gateway_port(),
            gateway_token: "x".repeat(64),
            cameras: vec![],
        };
        assert!(validate_recorder_settings(settings).is_ok());
        let _ = fs::remove_dir(root);
    }
}
