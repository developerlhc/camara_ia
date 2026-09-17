use base64::Engine;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Stdio,
    time::Duration,
};
use tauri::{Manager, State};
use tauri_plugin_opener::OpenerExt;
use tokio::{io::AsyncWriteExt, process::Command, sync::Mutex, time::timeout};

const LOCAL_IMAGE: &str = "ghcr.io/developerlhc/vigilay-local:v0.2.1-build-62";
const API_IMAGE: &str = "ghcr.io/developerlhc/vigilay-api:v0.2.1-build-62";
const FRIGATE_IMAGE: &str = "ghcr.io/blakeblackshear/frigate:0.18.0";
const BRIDGE: &str = include_str!("../../resources/bridge.py");
#[derive(Default)]
pub struct Operations(Mutex<()>);

#[derive(Deserialize)]
pub struct Settings {
    pub bdmysql: String,
    pub encryption_key: String,
    pub web_origin: String,
}

fn public_origin(value: &str) -> Result<String, String> {
    let url = url::Url::parse(value).map_err(|_| "Dirección HTTPS inválida")?;
    if url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/"
    {
        return Err("Usa sólo el origen HTTPS público de Vigilay, sin ruta ni credenciales".into());
    }
    Ok(url.origin().ascii_serialization())
}

fn validate(settings: &Settings) -> Result<String, String> {
    if settings.bdmysql.trim().is_empty()
        || settings.bdmysql.len() > 4096
        || settings.bdmysql.contains(['\r', '\n'])
    {
        return Err("Indica tu cadena BDMYSQL en una sola línea".into());
    }
    let key = base64::engine::general_purpose::STANDARD
        .decode(settings.encryption_key.trim())
        .map_err(|_| "La clave de cifrado debe ser base64 válido")?;
    if key.len() != 32 {
        return Err(
            "La clave debe corresponder a los 32 bytes originales de esta base; no la regeneres"
                .into(),
        );
    }
    public_origin(&settings.web_origin)
}

fn root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|p| p.join("deployment"))
        .map_err(|_| "No se pudo obtener el directorio de datos".into())
}

fn hidden(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.as_std_mut().creation_flags(0x08000000);
    }
    #[cfg(not(windows))]
    let _ = command;
}

async fn run(
    mut command: Command,
    input: Option<Vec<u8>>,
    seconds: u64,
) -> Result<std::process::Output, String> {
    hidden(&mut command);
    command
        .stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let mut child = command.spawn().map_err(|_| {
        "No se pudo ejecutar Docker. Instala Docker Desktop e inicia su motor Linux"
    })?;
    let operation = async {
        if let Some(data) = input {
            let mut stdin = child
                .stdin
                .take()
                .ok_or("No se pudo abrir el canal privado")?;
            stdin
                .write_all(&data)
                .await
                .map_err(|_| "No se pudo enviar la solicitud privada")?;
            drop(stdin);
        }
        child
            .wait_with_output()
            .await
            .map_err(|_| "No se pudo obtener el resultado".to_string())
    };
    timeout(Duration::from_secs(seconds), operation)
        .await
        .map_err(|_| {
            "La operación superó el tiempo permitido; comprueba Docker y reintenta".to_string()
        })?
}

async fn private_directory(path: &Path) -> Result<(), String> {
    fs::create_dir_all(path).map_err(|_| "No se pudo crear el directorio privado")?;
    #[cfg(windows)]
    {
        let mut who = Command::new("whoami.exe");
        who.args(["/user", "/fo", "csv", "/nh"]);
        let result = run(who, None, 10).await?;
        let output = String::from_utf8_lossy(&result.stdout);
        let sid = output
            .split('"')
            .find(|v| {
                v.starts_with("S-1-")
                    && v.chars()
                        .all(|c| c.is_ascii_digit() || c == '-' || c == 'S')
            })
            .ok_or("No se pudo identificar al propietario de los archivos privados")?;
        let mut acl = Command::new("icacls.exe");
        acl.arg(path)
            .args(["/inheritance:r", "/grant:r"])
            .arg(format!("*{sid}:(OI)(CI)F"))
            .arg("*S-1-5-18:(OI)(CI)F");
        if !run(acl, None, 10).await?.status.success() {
            return Err("No se pudo proteger la carpeta; no se escribieron credenciales".into());
        }
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))
            .map_err(|_| "No se pudo restringir la carpeta")?;
    }
    Ok(())
}

fn compose(root: &Path, args: &[&str]) -> Result<Command, String> {
    if !root.join("compose.private.json").is_file() {
        return Err("Primero prepara la instalación".into());
    }
    let mut command = Command::new("docker");
    command
        .current_dir(root)
        .args([
            "compose",
            "--project-name",
            "vigilay-desktop",
            "-f",
            "compose.private.json",
        ])
        .args(args);
    Ok(command)
}

async fn compose_ok(root: &Path, args: &[&str], seconds: u64) -> Result<(), String> {
    let output = run(compose(root, args)?, None, seconds).await?;
    if !output.status.success() {
        // Docker errors can contain resolved environment variables: never forward raw stderr.
        return Err("Docker no completó la operación. Comprueba motor Linux, espacio, acceso a GHCR y puertos 15000/18971/18554/18555. No se borraron datos.".into());
    }
    Ok(())
}

pub fn manifest(settings: &Settings, session: &str) -> Result<Value, String> {
    let origin = validate(settings)?;
    // Compose interpolates '$' even inside JSON; escape literal secrets before serialization.
    let env = json!({
        "BDMYSQL": settings.bdmysql.replace('$', "$$"),
        "CREDENTIAL_ENCRYPTION_KEY": settings.encryption_key.trim(), "SESSION_SECRET": session,
        "WEB_ORIGIN": origin, "VIGILAY_API_URL": origin, "CAMERA_STORAGE": "mysql",
        "LOCAL_AI_ENABLED": "false", "START_STREAM_AGENT_WITH_LOCAL": "false",
        "FRIGATE_API_URL": "http://frigate:5000", "FRIGATE_RESTREAM_URL": "rtsp://frigate:8554",
        "VIGILAY_LOCAL_PREFER_RESTREAM": "true", "V380_EXTERNAL_BRIDGE_HOST": "host.docker.internal"
    });
    Ok(json!({"services": {
        "vigilay-local": {
            "image": LOCAL_IMAGE, "init": true, "restart": "unless-stopped", "environment": env,
            "ports": ["127.0.0.1:15000:5000"], "extra_hosts": ["host.docker.internal:host-gateway"],
            "volumes": ["./identity:/app/.local", "./bridge.py:/opt/vigilay-desktop/bridge.py:ro", "./:/deployment"],
            "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"]
        },
        "frigate": {
            "image": FRIGATE_IMAGE, "restart": "unless-stopped", "shm_size": "256mb",
            "profiles": ["nvr"], "extra_hosts": ["host.docker.internal:host-gateway"],
            "ports": ["127.0.0.1:18971:8971", "127.0.0.1:18554:8554", "127.0.0.1:18555:8555/tcp", "127.0.0.1:18555:8555/udp"],
            "volumes": ["./frigate/config:/config", "./frigate/media:/media/frigate"],
            "tmpfs": ["/tmp/cache:size=268435456"]
        },
        "gateway": {
            "build": {"context": ".", "dockerfile": "Gateway.Dockerfile"},
            "profiles": ["cloud"], "restart": "unless-stopped", "environment": env,
            "volumes": ["./identity:/app/.local:ro"],
            "command": ["vigilay-frigate-gateway"], "healthcheck": {"disable": true},
            "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"]
        }
    }}))
}

#[tauri::command]
pub async fn diagnose(app: tauri::AppHandle) -> Result<Value, String> {
    let mut docker = Command::new("docker");
    docker.args(["version", "--format", "{{.Server.Os}}"]);
    let output = run(docker, None, 15).await?;
    let linux =
        output.status.success() && String::from_utf8_lossy(&output.stdout).trim() == "linux";
    let mut check = Command::new("docker");
    check.args(["compose", "version", "--short"]);
    let compose_ready = run(check, None, 15).await?.status.success();
    Ok(
        json!({"docker_linux":linux,"compose":compose_ready,"prepared":root(&app)?.join("compose.private.json").exists(),"directory":root(&app)?}),
    )
}

#[tauri::command]
pub async fn prepare(
    app: tauri::AppHandle,
    operations: State<'_, Operations>,
    settings: Settings,
) -> Result<Value, String> {
    let _guard = operations.0.lock().await;
    let data = manifest(
        &settings,
        &format!(
            "{}{}",
            uuid::Uuid::new_v4().simple(),
            uuid::Uuid::new_v4().simple()
        ),
    )?;
    let root = root(&app)?;
    if root.join("compose.private.json").exists() {
        return Err(
            "La instalación ya está preparada; inicia Local. No se sobrescribieron sus claves."
                .into(),
        );
    }
    private_directory(&root).await?;
    for directory in ["identity", "frigate/config", "frigate/media"] {
        fs::create_dir_all(root.join(directory))
            .map_err(|_| "No se pudieron crear los directorios")?;
    }
    fs::write(root.join("bridge.py"), BRIDGE).map_err(|_| "No se pudo escribir el conector")?;
    fs::write(root.join("Gateway.Dockerfile"), format!("FROM cloudflare/cloudflared:2026.9.1 AS tunnel\nFROM {API_IMAGE}\nCOPY --from=tunnel /usr/local/bin/cloudflared /usr/local/bin/cloudflared\n"))
        .map_err(|_| "No se pudo preparar el gateway")?;
    fs::write(root.join(".dockerignore"), "**\n!Gateway.Dockerfile\n")
        .map_err(|_| "No se pudo excluir los secretos del build")?;
    fs::write(
        root.join("compose.private.json"),
        serde_json::to_vec_pretty(&data).map_err(|_| "Configuración inválida")?,
    )
    .map_err(|_| "No se pudo guardar la configuración privada")?;
    Ok(json!({"prepared":true,"directory":root}))
}

#[tauri::command]
pub async fn start_local(
    app: tauri::AppHandle,
    operations: State<'_, Operations>,
) -> Result<Value, String> {
    let _guard = operations.0.lock().await;
    let root = root(&app)?;
    compose_ok(
        &root,
        &[
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "120",
            "vigilay-local",
        ],
        240,
    )
    .await?;
    Ok(json!({"url":"http://127.0.0.1:15000"}))
}

#[tauri::command]
pub async fn bridge(
    app: tauri::AppHandle,
    operations: State<'_, Operations>,
    payload: Value,
) -> Result<Value, String> {
    let _guard = operations.0.lock().await;
    let action = payload.get("action").and_then(Value::as_str).unwrap_or("");
    if ![
        "catalog",
        "configure_scope",
        "cameras",
        "save_camera",
        "plan",
        "export",
        "bind",
        "password",
    ]
    .contains(&action)
    {
        return Err("Operación no permitida".into());
    }
    let input = serde_json::to_vec(&payload).map_err(|_| "Solicitud inválida")?;
    if input.len() > 65536 {
        return Err("Solicitud demasiado grande".into());
    }
    let output = run(
        compose(
            &root(&app)?,
            &[
                "exec",
                "-T",
                "vigilay-local",
                "python",
                "/opt/vigilay-desktop/bridge.py",
            ],
        )?,
        Some(input),
        90,
    )
    .await?;
    let response: Value = serde_json::from_slice(&output.stdout)
        .map_err(|_| "Local no respondió; inícialo y verifica la configuración")?;
    if !output.status.success() || response.get("ok") != Some(&Value::Bool(true)) {
        return Err(response
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("No se completó la operación")
            .to_string());
    }
    if ["configure_scope", "save_camera", "bind"].contains(&action) {
        compose_ok(&root(&app)?, &["restart", "vigilay-local"], 45).await?;
    }
    Ok(response["result"].clone())
}

#[tauri::command]
pub async fn start_frigate(
    app: tauri::AppHandle,
    operations: State<'_, Operations>,
) -> Result<Value, String> {
    let _guard = operations.0.lock().await;
    let root = root(&app)?;
    if !root.join("frigate/config/.vigilay-managed.json").exists() {
        return Err("Revisa y exporta primero las cámaras de esta sede".into());
    }
    // Recreate only our container so bind-mounted config changes take effect, then wait.
    compose_ok(
        &root,
        &[
            "up",
            "-d",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "150",
            "frigate",
        ],
        300,
    )
    .await?;
    Ok(
        json!({"started":true,"url":"https://127.0.0.1:18971","next":"Espera a que Frigate esté listo; vincula las cámaras y establece tu contraseña."}),
    )
}

#[tauri::command]
pub async fn connect_gateway(
    app: tauri::AppHandle,
    operations: State<'_, Operations>,
) -> Result<Value, String> {
    let _guard = operations.0.lock().await;
    let root = root(&app)?;
    if !root.join("identity/vigilay-local.json").exists() {
        return Err("Selecciona primero la empresa y sede".into());
    }
    if !root.join("frigate/config/.vigilay-managed.json").exists() {
        return Err("Exporta e inicia Frigate antes de conectar esta sede".into());
    }
    compose_ok(&root, &["up", "-d", "--build", "gateway"], 300).await?;
    Ok(
        json!({"started":true,"note":"El gateway publicará una conexión autenticada por sede, sin requerir dominio propio."}),
    )
}

#[tauri::command]
pub fn open_page(app: tauri::AppHandle, page: String) -> Result<(), String> {
    let url = match page.as_str() {
        "local" => "http://127.0.0.1:15000",
        "frigate" => "https://127.0.0.1:18971",
        "docker" => "https://docs.docker.com/desktop/setup/install/windows-install/",
        _ => return Err("Enlace no permitido".into()),
    };
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(|_| "No se pudo abrir el navegador".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn settings() -> Settings {
        Settings {
            bdmysql: "Server=example;Pwd=test$only".into(),
            encryption_key: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=".into(),
            web_origin: "https://example.bunny.run".into(),
        }
    }
    #[test]
    fn only_https_origins() {
        for value in [
            "http://x.test",
            "https://u:p@x.test",
            "https://x.test/login",
            "https://x.test?key=x",
        ] {
            assert!(public_origin(value).is_err());
        }
        assert_eq!(
            public_origin("https://example.bunny.run/").unwrap(),
            "https://example.bunny.run"
        );
    }
    #[test]
    fn private_ports_and_no_docker_socket() {
        let value = manifest(&settings(), "synthetic-session").unwrap();
        let text = value.to_string();
        assert!(!text.contains("docker.sock"));
        assert_eq!(
            value["services"]["vigilay-local"]["ports"],
            json!(["127.0.0.1:15000:5000"])
        );
        assert_eq!(
            value["services"]["frigate"]["ports"][0],
            "127.0.0.1:18971:8971"
        );
        assert!(text.contains("test$$only"));
    }
    #[test]
    fn rejects_invalid_key() {
        let mut s = settings();
        s.encryption_key = "secret".into();
        assert!(manifest(&s, "test").is_err());
    }
}
