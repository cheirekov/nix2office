# RDP thin client (роли office / hybrid / thin)

Nix2office поддържа три роли за една машина, задавани с role в machine.toml:

- **office** — пълният локален офис десктоп, както досега.
- **hybrid** — офисът плюс FreeRDP thin client (X11 клиент xfreerdp).
- **thin** — минимална kiosk система само за RDP, без XFCE, браузър, офис, PDF, Nextcloud, ArtCraft и допълнителни програми.

Клиентът е FreeRDP 3 от текущия nixpkgs pin (пакети freerdp и xfreerdp). Поддържа пълна отдалечена сесия и RemoteApp (отделни Windows програми като локални прозорци), с пренасочване на смарткарта, clipboard, аудио, локални дискове и USB.

## Конфигурация в machine.toml

Пример за роля hybrid:

    role = "hybrid"

    [thin_client]
    credentials = "interactive"   # или "sops"
    redirect = ["smartcard", "clipboard", "audio", "drives", "usb"]

    [[thin_client.profiles]]
    name = "windows"
    host = "192.0.2.10"
    user = "accountant"
    port = 3389
    remote_apps = ["Accounting"]

Полетата:

- role — office, hybrid или thin.
- thin_client.credentials — interactive (пита за парола при всяко свързване, нищо не се записва) или sops (криптирана парола, виж по-долу).
- thin_client.redirect — подмножество от smartcard, clipboard, audio, drives, usb.
- thin_client.profiles — един или повече RDP профила. Всеки има name, host, user, port (по подразбиране 3389) и remote_apps (списък от RemoteApp alias-и).
- Ролята hybrid или thin изисква поне един профил.

Паролата не се пише в machine.toml. При interactive тя се въвежда на екрана на FreeRDP; при sops се съхранява криптирана в частния deployment.

## Парола с sops

При credentials = "sops" и роля hybrid/thin помощникът създава rdp.yaml в частния .deployment, криптиран с host и operator age ключовете. На инсталираната машина sops-nix я разшифрова в /run/secrets/rdp-password (mode 0400, собственик — офис потребителя). Launcher-ът чете файла и подава паролата през частен временен .rdp файл, затова тя не се появява в списъка на процесите.

При interactive файлът не съществува и FreeRDP пита за входни данни.

## RemoteApp

RemoteApp изисква Windows страната да публикува програмата като RemoteApp (например чрез RDP Wrapper/RemoteApp настройка). В remote_apps може да се запише или пълният път до програмата, например C:\Program Files (x86)\Info Partner\Expecta\Client\ExpectaClient.exe, или краткото име на публикувания alias. Launcher-ът го стартира съответно с /app:program:<път> или /app:program:||<alias>.

Всеки профил получава .desktop launcher за пълна сесия, а всеки RemoteApp alias — отделен launcher. В thin режим първият профил се стартира автоматично след влизане.

## Роля thin

- LightDM auto-login за потребителя и openbox като минимален прозоречен мениджър (без XFCE).
- Първият RDP профил се стартира автоматично след влизане.
- Браузър, офис, PDF, Nextcloud, ArtCraft, допълнителни програми и MS core fonts/офис fallbacks не се инсталират.

При избран smartcard в redirect се включва pcscd (с вградения CCID драйвер), за да работи пренасочването на смарткарти/КЕП.

### Устойчив старт и fallback меню

Kiosk процесът първо изчаква decrypted sops паролата (когато credentials = "sops") и TCP достижимостта на избрания Windows хост, след което пуска xfreerdp и при неуспех повтаря опита с backoff. Така забавянето на мрежата при първото зареждане не оставя празен екран.

Ако свързването не успее или потребителят затвори сесията, остава минимална openbox сесия с меню от десния бутон върху работния плот:

- повторен старт на всеки RDP профил и на всеки RemoteApp alias;
- настройки на мрежата (nm-connection-editor), терминал, звук (pavucontrol) и системен монитор (htop);
- рестартиране и изключване.

За тези действия в thin режим се включва polkit с правила само за локалния потребител: управление на NetworkManager връзки и power-off/reboot. Потребителят остава без sudo.

## Windows ограничения

Стандартен Windows 11 позволява една активна RDP сесия наведнъж и не поддържа едновременен локален и отдалечен вход с един и същи акаунт. За няколко потребителя или паралелни сесии е нужен RDP Wrapper или съответната server лицензна настройка. RemoteApp и smartcard redirection зависят от конфигурацията на Windows хост-а.

## Проверка

Тестовете на живо обхващат пълна сесия, RemoteApp, clipboard, аудио, кирилица и КЕП през smartcard redirection. Локалният КЕП тест на Linux + Firefox е отделен потребителски тест, без промяна в тази функция.
