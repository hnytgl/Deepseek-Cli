"""
deepseek_cli.completions -- Shell completion scripts for bash/zsh/fish.

Usage:
    deepseek --completions bash   >> ~/.bashrc
    deepseek --completions zsh    >> ~/.zshrc
    deepseek --completions fish   > ~/.config/fish/completions/deepseek.fish
"""

from __future__ import annotations

BASH_COMPLETION = '''
_deepseek_completions() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    opts="--help --version --cwd --model --base-url --api-key --api-timeout --api-retries
--yes -y --approval --sandbox --no-shell --allow-install-tools --allow-command --deny-command
--save-policy --show-policy --session --save-sensitive --resume --sessions --replay-session
--no-stream --max-steps --max-context-chars --temperature -q --quiet --json --plain
--fullscreen --reasoning --thinking-budget --theme --layout --expanded-output --doctor
--self-update --completions"

    if [[ ${cur} == -* ]]; then
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
    fi

    case "${prev}" in
        --cwd)
            COMPREPLY=( $(compgen -d -- ${cur}) )
            return 0
            ;;
        --model)
            COMPREPLY=( $(compgen -W "deepseek-flash deepseek-v4-flash deepseek-v4-pro" -- ${cur}) )
            return 0
            ;;
        --approval)
            COMPREPLY=( $(compgen -W "suggest auto-edit full-auto ask auto read-only" -- ${cur}) )
            return 0
            ;;
        --sandbox)
            COMPREPLY=( $(compgen -W "workspace unrestricted" -- ${cur}) )
            return 0
            ;;
        --theme)
            COMPREPLY=( $(compgen -W "default ocean mono high-contrast" -- ${cur}) )
            return 0
            ;;
        --layout)
            COMPREPLY=( $(compgen -W "balanced logs-right stacked" -- ${cur}) )
            return 0
            ;;
        --completions)
            COMPREPLY=( $(compgen -W "bash zsh fish" -- ${cur}) )
            return 0
            ;;
    esac
}
complete -F _deepseek_completions deepseek
complete -F _deepseek_completions deepseek-cli
'''

ZSH_COMPLETION = '''#compdef deepseek deepseek-cli

_deepseek() {
    local -a options
    options=(
        '--help[Show help]'
        '--version[Show version]'
        '--cwd[Workspace directory]:directory:_files -/'
        '--model[DeepSeek model]:model:(deepseek-flash deepseek-v4-flash deepseek-v4-pro)'
        '--base-url[API base URL]:url:'
        '--api-key[API key]:key:'
        '--api-timeout[API timeout seconds]:seconds:'
        '--api-retries[API retry count]:count:'
        '--yes[Auto-approve all tools]'
        '-y[Auto-approve all tools]'
        '--approval[Approval mode]:mode:(suggest auto-edit full-auto ask auto read-only)'
        '--sandbox[Sandbox mode]:mode:(workspace unrestricted)'
        '--no-shell[Disable shell tools]'
        '--allow-command[Allow command]:command:'
        '--deny-command[Deny command]:command:'
        '--session[Session name]:name:'
        '--resume[Resume latest session]'
        '--reasoning[Enable reasoning mode]'
        '--thinking-budget[Thinking token budget]:tokens:'
        '--theme[TUI theme]:theme:(default ocean mono high-contrast)'
        '--layout[Fullscreen layout]:layout:(balanced logs-right stacked)'
        '-q[Quiet mode]'
        '--quiet[Quiet mode]'
        '--json[JSON output]'
        '--plain[Plain text mode]'
        '--fullscreen[Fullscreen TUI]'
        '--doctor[Check installation]'
        '--self-update[Self update]'
        '--completions[Generate completions]:shell:(bash zsh fish)'
    )
    _arguments -s $options '*:prompt:'
}
_deepseek "$@"
'''

FISH_COMPLETION = '''
complete -c deepseek -l help -d "Show help"
complete -c deepseek -l version -d "Show version"
complete -c deepseek -l cwd -d "Workspace directory" -r -F
complete -c deepseek -l model -d "DeepSeek model" -r -a "deepseek-flash deepseek-v4-flash deepseek-v4-pro"
complete -c deepseek -l approval -d "Approval mode" -r -a "suggest auto-edit full-auto ask auto read-only"
complete -c deepseek -l sandbox -d "Sandbox mode" -r -a "workspace unrestricted"
complete -c deepseek -l theme -d "TUI theme" -r -a "default ocean mono high-contrast"
complete -c deepseek -l layout -d "Fullscreen layout" -r -a "balanced logs-right stacked"
complete -c deepseek -s y -l yes -d "Auto-approve all tools"
complete -c deepseek -s q -l quiet -d "Quiet mode"
complete -c deepseek -l json -d "JSON output"
complete -c deepseek -l plain -d "Plain text mode"
complete -c deepseek -l fullscreen -d "Fullscreen TUI"
complete -c deepseek -l reasoning -d "Enable reasoning mode"
complete -c deepseek -l no-shell -d "Disable shell tools"
complete -c deepseek -l doctor -d "Check installation"
complete -c deepseek -l completions -d "Generate completions" -r -a "bash zsh fish"
'''


def get_completion_script(shell: str) -> str:
    """Return the completion script for the given shell."""
    scripts = {
        "bash": BASH_COMPLETION,
        "zsh": ZSH_COMPLETION,
        "fish": FISH_COMPLETION,
    }
    if shell not in scripts:
        raise ValueError(f"Unsupported shell: {shell}. Choose from: bash, zsh, fish")
    return scripts[shell]
