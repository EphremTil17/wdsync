function wdsync-init --description "Delegate to the Python wdsync init command"
    if command -sq wdsync
        command wdsync init $argv
        return $status
    end

    set -l script_dir (dirname (status --current-filename))
    set -l project_root (realpath "$script_dir/../..")
    uv run --project "$project_root" wdsync init $argv
end
