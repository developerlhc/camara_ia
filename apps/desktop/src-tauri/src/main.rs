#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod deployment;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(deployment::Operations::default())
        .invoke_handler(tauri::generate_handler![
            deployment::diagnose,
            deployment::prepare,
            deployment::start_local,
            deployment::bridge,
            deployment::start_frigate,
            deployment::connect_gateway,
            deployment::open_page
        ])
        .run(tauri::generate_context!())
        .expect("No se pudo iniciar Vigilay Desktop");
}
