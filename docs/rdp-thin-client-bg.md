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
    fullscreen = true             # стартира RDP в пълен екран

    [[thin_client.profiles]]
    name = "windows"
    host = "192.0.2.10"
    user = "accountant"
    port = 3389
    remote_apps = ["Accounting"]

Полетата:

- role — office, hybrid или thin.
- thin_client.credentials — interactive (пита за парола при всяко свързване, нищо не се записва) или sops (криптирана парола, виж по-долу).
- thin_client.redirect — подмножество от smartcard, clipboard, audio, drives, usb. При drives се споделя само локалната папка ~/Shared като мрежов диск „Shared“ (създава се автоматично, ако липсва), а не цялата домашна папка.
- thin_client.fullscreen — true/false (по подразбиране false). Стартира RDP сесията в пълен екран; излизане/връщане с Ctrl+Alt+Enter.
- thin_client.unicode_keyboard — true/false (по подразбиране false). При RemoteApp изпраща въвеждането като Unicode, за да достигне кирилица до програмата; може да наруши някои Ctrl+буква комбинации.
- thin_client.gfx — auto, rfx или software (по подразбиране auto). Начин на изобразяване на RDP: auto (договаря се, обикновено H.264), rfx (RemoteFX кодек вместо H.264) или software (RemoteFX + софтуерен GDI). Полезно за диагностика на „черни“ области при стари програми.
- thin_client.profiles — един или повече RDP профила. Всеки има name, host, user, port (по подразбиране 3389) и remote_apps (списък от RemoteApp alias-и).
- Ролята hybrid или thin изисква поне един профил.

Паролата не се пише в machine.toml. При interactive тя се въвежда на екрана на FreeRDP; при sops се съхранява криптирана в частния deployment.

## Парола с sops

При credentials = "sops" и роля hybrid/thin помощникът създава rdp.yaml в частния .deployment, криптиран с host и operator age ключовете. На инсталираната машина sops-nix я разшифрова в /run/secrets/rdp-password (mode 0400, собственик — офис потребителя). Launcher-ът чете файла и подава паролата през частен временен .rdp файл, затова тя не се появява в списъка на процесите.

При interactive файлът не съществува и FreeRDP пита за входни данни.

## RemoteApp

RemoteApp изисква Windows страната да публикува програмата като RemoteApp (например чрез RDP Wrapper/RemoteApp настройка). В remote_apps може да се запише или пълният път до програмата, например C:\Program Files (x86)\Info Partner\Expecta\Client\ExpectaClient.exe, или краткото име на публикувания alias. Launcher-ът го стартира съответно с /app:program:<път> или /app:program:||<alias>.

Всеки профил получава .desktop launcher за пълна сесия, а всеки RemoteApp alias — отделен launcher. Запис в remote_apps, който е пълен път до изпълним файл, получава и втори launcher „Alternate shell“ (виж по-долу). В thin режим първият профил се стартира автоматично след влизане.

В менюто и на работния плот RemoteApp записите се показват с кратко име: за пълен път се взима името на програмата без разширението (например ExpectaClient), а кратък alias се показва както е.

## Клавиатура в RemoteApp (App mode)

В пълна RDP сесия превключването на езика (Alt+Shift) се управлява от Windows и работи. В RemoteApp режим (отделна програма) Windows не синхронизира автоматично клиентската клавиатурна подредба и може да остане на езика по подразбиране на сървъра. Това е ограничение на RemoteApp, а не на FreeRDP клиента: решението е от страна на Windows — инсталирана българска подредба на хост-а и включен keyboard sync, евентуално с изричен layout за сесията.

Клиентска алтернатива, когато програмата трябва да приема кирилица: unicode_keyboard = true кара FreeRDP да изпраща въвеждането като Unicode (вместо scancodes), така че кирилицата достига до RemoteApp програмата. Цената е, че някои Ctrl+буква комбинации може да спрат да се разпознават.

Друг вариант е да не се използва RemoteApp, а програмата да се пусне като „alternate shell“ в пълна сесия (/shell:<път до изпълнимия файл>). Тогава клавиатурата се държи като в пълна сесия (Alt+Shift работи), но програмата е сама в сесията без Windows taskbar. Този режим изисква пълен път до изпълнимия файл; кратко публикувано име (alias) няма път, който да се подаде на /shell.

## Alternate shell (пълна сесия само за една програма)

При RemoteApp отделните прозорци се изобразяват по различен път от цял десктоп. Някои стари Windows програми (често Delphi/старо GDI) в RemoteApp показват черни подменюта или увисват. За тях се генерира допълнителен launcher „Alternate shell“: FreeRDP влиза в пълна сесия, но вместо explorer.exe стартира избраната програма (чрез /shell:<път>). Това запазва нормалното изобразяване и клавиатурата на пълна сесия, а потребителят вижда само самата програма без taskbar.

Alternate shell launcher се създава само когато записът в remote_apps е пълен път до изпълним файл (например C:\Program Files (x86)\Info Partner\Expecta\Client\ExpectaClient.exe). За кратко alias име няма такъв launcher.

## Диагностика на изобразяването

Ако програма в RemoteApp показва черни области или увисва, първо се опита Alternate shell режимът. Ако проблемът трябва да се провери и в RemoteApp, thin_client.gfx превключва пътя на изобразяване:

- auto — договаря се с Windows (обикновено H.264/AVC420 през VA-API).
- rfx — принудителен RemoteFX кодек вместо H.264.
- software — RemoteFX + софтуерен GDI (най-консервативният път).

## Видео

FreeRDP 3 преговаря GFX/H.264 с Windows и декодира през FFmpeg, който е вграден в пакета. Инсталаторът добавя и подходящия VA-API драйвер за открития хардуер (например intel-vaapi-driver за Intel Bay Trail) също и в thin роля. Дали декодирането е на CPU или GPU зависи от VA-API пътя на FreeRDP и може да се провери с измерване при нужда.

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

Kiosk-ът повтаря опита само при мрежова/свързваща грешка (например мрежата още не е готова при зареждане). Когато потребителят излезе от Windows или прекъсне сесията, нова сесия НЕ се стартира автоматично — остава менюто.

За тези действия в thin режим се включва polkit с правила само за локалния потребител: управление на NetworkManager връзки и power-off/reboot. Потребителят остава без sudo.

## Живот на RDP сесията (натрупване на сесии)

Когато потребителят излезе от RemoteApp програмата или затвори клиента, FreeRDP прекъсва връзката, но Windows по подразбиране оставя сесията в състояние „disconnected“. С RDP Wrapper и MaxDisconnectionTime = 0 / MaxIdleTime = 0 тези сесии се натрупват и могат да блокират нови влизания; това се видя на тестовия хост като залежали rdp-tcp сесии.

Поправката е настройка от страна на Windows хост-а, защото FreeRDP клиентът не може да принуди сървъра да изтрие сесия, която той оставя отворена: Local Group Policy → Computer Configuration → Administrative Templates → Windows Components → Remote Desktop Services → Remote Desktop Session Host → Session Time Limits — задайте край на прекъснатите и неактивните сесии (например няколко минути) и включете изтриване след изтичане, или разрешете logoff при прекъсната връзка.

## Състояние на RemoteApp (очаквани проблеми)

- Някои стари Windows програми (Delphi/GDI, например ExpectaClient) в RemoteApp показват черни подменюта и после увисват. Първо се пробва thin_client.gfx = "rfx", ако не помогне — "software" (виж „Диагностика на изобразяването“ по-горе).
- Alternate shell в момента отваря пълна RDP сесия, но не стартира надеждно избраната програма; това е известно ограничение и се уточнява.

## Windows ограничения

Стандартен Windows 11 позволява една активна RDP сесия наведнъж и не поддържа едновременен локален и отдалечен вход с един и същи акаунт. За няколко потребителя или паралелни сесии е нужен RDP Wrapper или съответната server лицензна настройка. RemoteApp и smartcard redirection зависят от конфигурацията на Windows хост-а.

## Проверка

Тестовете на живо обхващат пълна сесия, RemoteApp, clipboard, аудио, кирилица и КЕП през smartcard redirection. Локалният КЕП тест на Linux + Firefox е отделен потребителски тест, без промяна в тази функция.
