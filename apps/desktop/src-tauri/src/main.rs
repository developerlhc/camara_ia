#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod deployment;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WindowEvent,
};

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(deployment::Operations::default())
        .setup(|app| {
            let open = MenuItem::with_id(app, "open", "Abrir Vigilay", true, None::<&str>)?;
            let quit =
                MenuItem::with_id(app, "quit", "Salir y detener grabación", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &quit])?;
            let mut tray = TrayIconBuilder::new()
                .menu(&menu)
                .tooltip("Vigilay Desktop");
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.on_menu_event(|app, event| match event.id.as_ref() {
                "open" => show_main_window(app),
                "quit" => app.exit(0),
                _ => {}
            })
            .on_tray_icon_event(|tray, event| {
                if let TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } = event
                {
                    show_main_window(tray.app_handle());
                }
            })
            .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            deployment::login,
            deployment::logout,
            deployment::ensure_stream_agent,
            deployment::catalog,
            deployment::create_tenant,
            deployment::create_site,
            deployment::cameras,
            deployment::start_live,
            deployment::heartbeat_live,
            deployment::stop_live,
            deployment::create_camera,
            deployment::recorder_settings,
            deployment::choose_recording_directory,
            deployment::save_recorder_settings,
            deployment::register_recording_camera,
            deployment::sync_recording_cameras,
            deployment::start_recorder,
            deployment::stop_recorder,
            deployment::recorder_status,
            deployment::open_recordings,
            deployment::open_web
        ])
        .run(tauri::generate_context!())
        .expect("No se pudo iniciar Vigilay Desktop");
}
