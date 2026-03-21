function wdsync --description "Delegate to the Python wdsync CLI"
    if command -sq wdsync
        command wdsync $argv
        return $status
    end

    set -l script_dir (dirname (status --current-filename))
    set -l project_root (realpath "$script_dir/../..")
    uv run --project "$project_root" wdsync $argv
end
