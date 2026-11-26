# Keep one controller per kiosk user, with the lock closed in child clients.
exec 9>"$XDG_RUNTIME_DIR/nix2office-connections.lock" || exit 1
"$flock" -n 9 || exit 0

section=main
notice=

run_selection() {
    local selection=$1 status
    notice=
    run_action "$selection" 9>&-
    status=$?
    if (( status != 0 )); then
        if [[ $selection == main-* ]]; then
            notice='Връзката или действието не завърши успешно. Опитай отново или отвори Настройки.'
        else
            notice='Действието не завърши успешно.'
        fi
    fi
}

run_automatic() {
    local choice status
    local network_label='Настройки на мрежата'
    while ! run_action auto 9>&-; do
        choice=$(GSK_RENDERER=cairo "$zenity" --question --title='Връзката не успя' \
            --text='Провери мрежовата връзка или опитай отново.' \
            --ok-label='Опитай пак' --extra-button="$network_label" \
            --cancel-label='Към връзките' 9>&-)
        status=$?
        if [[ $choice == "$network_label" ]]; then
            run_selection network
            return
        fi
        if (( status != 0 )); then
            return
        fi
    done
}

if [[ ${1-} == --auto ]]; then
    run_automatic
fi

while :; do
    case $section in
        main) title=Връзки; back=Затвори ;;
        settings) title=Настройки; back=Назад ;;
        diagnostics) title=Диагностика; back=Назад ;;
        power) title='Изключване и рестарт'; back=Назад ;;
    esac
    declare -n rows="rows_$section"
    text=$notice
    if [[ $section == main ]]; then
        text=${notice:-Избери връзка или действие.}
        if [[ -n $usb_hint ]]; then
            text+=$'\n'"$usb_hint"
        fi
    fi
    chosen=$(GSK_RENDERER=cairo "$zenity" --list --title="$title" --text="$text" --width=560 --height=460 \
        --ok-label=Отвори --cancel-label="$back" --hide-column=1 --print-column=1 \
        --column=ID --column=Име --column=Вид -- "${rows[@]}" 9>&-)
    status=$?
    if (( status != 0 )); then
        # Cancel returns from a submenu. GUI errors leave the Openbox fallback usable.
        if (( status != 1 )) || [[ $section == main ]]; then
            exit 0
        fi
        section=main
        notice=
        continue
    fi
    case $chosen in
        settings|diagnostics|power)
            section=$chosen
            notice=
            ;;
        '') ;;
        *) run_selection "$chosen" ;;
    esac
done
