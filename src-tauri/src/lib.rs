mod commands;
mod discovery;
mod git_service;
mod models;
mod store;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            commands::load_app_state,
            commands::save_repositories,
            commands::discover_repositories,
            commands::refresh_repositories,
            commands::pull_repositories,
            commands::commit_repositories,
            commands::push_repositories,
            commands::load_log_entries,
            commands::load_commit_view,
        ])
        .run(tauri::generate_context!())
        .expect("error while running GitHub Batch Manager");
}
