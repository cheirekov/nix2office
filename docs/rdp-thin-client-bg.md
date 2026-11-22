# RDP thin client (роли office / hybrid / thin)

Nix2office поддържа три роли за една машина, задавани с role в machine.toml:

- **office** — пълният локален офис десктоп, както досега.
- **hybrid** — офисът плюс FreeRDP thin client (X11 клиент xfreerdp).
- **thin** — минимална kiosk система само за RDP, без XFCE, браузър, офис, PDF, Nextcloud, ArtCraft и допълнителни програми.

Пълната сесия и RemoteApp (App режим) ползват X11 клиента `xfreerdp` от FreeRDP 3. Поддържа се пренасочване на смарткарта, clipboard, аудио, локални дискове и USB.

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
- thin_client.redirect — подмножество от smartcard, clipboard, audio, drives, usb. Киоскът винаги споделя локалната папка `~/Shared` като `Shared`. При Hybrid това споделяне се включва с `drives`.
- thin_client.fullscreen — true/false (по подразбиране false). Стартира RDP сесията в пълен екран; излизане/връщане с Ctrl+Alt+Enter.
- thin_client.unicode_keyboard — true/false (по подразбиране false). При true RemoteApp използва `/kbd:unicode:on` и изпраща символи от локалната клавиатурна подредба.
- thin_client.gfx — auto, rfx или software (по подразбиране auto). Избира графичния режим на пълната сесия и Alternate shell. RemoteApp използва договарянето по подразбиране на клиента.
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

В пълна RDP сесия превключването се управлява от Windows. За RemoteApp с `unicode_keyboard = true` използвайте локалната комбинация за смяна на подредбата и проверете въведения текст в програмата. При теста на ExpectaClient с `xfreerdp` и тази настройка превключването е потвърдено от потребителя. SDL3 вариантите бяха тествани отделно и превключването остана блокирано.

Друг вариант е да не се използва RemoteApp, а програмата да се пусне като „alternate shell“ в пълна сесия (/shell:<път до изпълнимия файл>). Тогава клавиатурата се държи като в пълна сесия (Alt+Shift работи), но програмата е сама в сесията без Windows taskbar. Този режим изисква пълен път до изпълнимия файл; кратко публикувано име (alias) няма път, който да се подаде на /shell.

## Alternate shell (пълна сесия само за една програма)

При RemoteApp отделните прозорци се изобразяват по различен път от цял десктоп. Някои стари Windows програми (често Delphi/старо GDI) в RemoteApp показват черни подменюта или увисват. За тях се генерира допълнителен launcher „Alternate shell“: FreeRDP влиза в пълна сесия, но вместо explorer.exe стартира избраната програма (чрез /shell:<път>). Това запазва нормалното изобразяване и клавиатурата на пълна сесия, а потребителят вижда само самата програма без taskbar.

Alternate shell launcher се създава само когато записът в remote_apps е пълен път до изпълним файл (например C:\Program Files (x86)\Info Partner\Expecta\Client\ExpectaClient.exe). За кратко alias име няма такъв launcher.

## Диагностика на изобразяването

При черни менюта или увисване в RemoteApp може да се провери същата програма в пълна RDP сесия. За пълната сесия `thin_client.gfx` избира графичния режим:

- auto — договаря се с Windows (обикновено H.264/AVC420 през VA-API).
- rfx — принудителен RemoteFX кодек вместо H.264.
- software — RemoteFX + софтуерен GDI (най-консервативният път).

## Видео

FreeRDP 3 преговаря GFX/H.264 с Windows и декодира през FFmpeg, който е вграден в пакета. Инсталаторът добавя и подходящия VA-API драйвер за открития хардуер (например intel-vaapi-driver за Intel Bay Trail) също и в thin роля. Дали декодирането е на CPU или GPU зависи от VA-API пътя на FreeRDP и може да се провери с измерване при нужда.

## Роля thin

- LightDM auto-login за потребителя и openbox като минимален прозоречен мениджър (без XFCE).
- Първият RDP профил се стартира автоматично след влизане.
- Браузър, офис, PDF, Nextcloud, ArtCraft, допълнителни програми и MS core fonts/офис fallbacks не се инсталират.

### КЕП с USB токен през Windows RDP

За ролята `thin` магьосникът пита дали ще се използва КЕП, с подразбиращ
се отговор „Не“. При „Да“ избери доставчик или „Ще избера по-късно“.
Можеш да подготвиш машината без включен токен. Изборът записва
`thin_client.kep_provider` в `machine.toml` и добавя `smartcard` в
`thin_client.redirect`. Това включва PC/SC с драйвера CCID на киоска и
пренасочване със `/smartcard` в FreeRDP. Името на доставчика се показва
в прегледа на конфигурацията.

За ръчна промяна добави `smartcard` към съществуващия списък `redirect`
и задай `kep_provider` на `b-trust`, `infonotary`, `stampit`,
`evrotrust`, `edocs`, `other` или `unspecified`. За изключване премахни
`smartcard` и остави `kep_provider = ""`. Старите конфигурации без
`kep_provider` продължават да използват съществуващия си списък `redirect`.

Следните USB идентификатори са в `Info.plist` на пакета CCID 1.7.1 от
заключения nixpkgs:

| Четец | USB VID:PID | Състояние |
| --- | --- | --- |
| ACS ACR39U ICC Reader | `072f:b100` | Потвърдено пренасочване при включване на целия токен във вече отворена RDP сесия и след повторно свързване. |
| ACS ACR38U-CCID | `072f:90cc` | В пакета. За други ACR38 ревизии свери USB ID. |
| Circle CCR7115 ICC | `31aa:7001` | В пакета. Свери USB ID за конкретния CCR7115B вариант. |
| Circle CIR115 ICC | `31aa:1000` | В пакета. Свери USB ID за конкретния CIR115 вариант. |
| HID Omnikey 1021 | `076b:1021` | В пакета. |

ACS описва ACR39T-A1 като USB CCID. За ACR39T-A1 и ACR38C-SPC-R,
посочени от InfoNotary, свери точния USB ID на устройството преди
добавяне на отделен драйвер. Търговското име само по себе си не
потвърждава коя ревизия е включена в пакета.
[Списък на CCID](https://ccid.apdu.fr/ccid/iProduct.html),
[ACS ACR39T-A1](https://www.acs.com.hk/en/products/331/acr39t-a1-smart-card-reader),
[B-Trust](https://www.b-trust.bg/client-center/system-requirements),
[InfoNotary](https://repository.infonotary.com/ra/install/Minimum_Requirements_BG.pdf),
[StampIT](https://www.stampit.org/en/page/795).

На Windows хоста подготви софтуера за конкретната карта и браузъра
според доставчика. За Evrotrust и eDocs провери дали услугата е на
физически носител или е дистанционен подпис.
[Evrotrust](https://evrotrust.com/bg/udostovereniya-i-polezni-vruzki/),
[Регистър на КРС](https://crc.bg/bg/rubriki/560/elektronni-udostoveritelni-uslugi).
Приемането изисква реално подписване с валиден сертификат в Windows
сесията. До този момент е потвърдено пренасочването на ACR39U.

### USB флашки в отворена RDP сесия

В магьосника за Thin/Kiosk включи „USB флашки в Windows RDP“ или запиши
`usb_storage = true` в `[thin_client]`. Когато включиш сменяема USB
памет с FAT, exFAT или NTFS дял, той се появява в Windows Explorer като
`\\tsclient\USB-1`, `\\tsclient\USB-2` и т.н. При няколко дяла всеки
поддържан дял получава отделно име. Можеш да включваш флашки и след вход
в RDP. Достъпът е само за четене.

В този режим FreeRDP обявява само точките за монтиране от USB услугата
на киоска. `Shared` остава достъпна за четене и запис. В менюто на
киоска **Файлов мениджър — Shared** отваря тази папка в Thunar.
Общото USB пренасочване е изключено в този режим. КЕП използва
пренасочване на смарткарта.

За безопасно изваждане затвори файловете от флашката в Windows. Ако
си на цял екран, използвай Ctrl+Alt+Enter, за да стигнеш до работния
плот на киоска. С десен бутон отвори **Безопасно изваждане на USB**.
Диалогът показва името в Windows, етикета и размера на всеки диск.
Избери диск, натисни **Извади** и изчакай потвърждението.
При няколко дяла командата демонтира всички дялове на избраната флашка.

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

- В ExpectaClient черните подменюта и увисването се възпроизведоха с `xfreerdp` и при опитите с RemoteFX и софтуерен GDI. Причината остава непотвърдена. Пълната RDP сесия е провереният вариант за тази програма.
- На 21 ноември 2026 г. потребителят потвърди превключване между кирилица и латиница в Word (`WINWORD.EXE`) в RemoteApp след рестарт на киоска. Тестът е с `xfreerdp`, `unicode_keyboard = true` и `fullscreen = true`.
- При нов профил с RemoteApp помощникът пита дали да включи Unicode вход от локалната клавиатурна подредба. Предварителният избор е включен, за да възпроизведе потвърдения WinAPP вариант.
- Alternate shell в момента отваря пълна RDP сесия, но не стартира надеждно избраната програма; Windows 11 Pro игнорира client alternate shell заявката — ограничение на client SKU-то.

## Windows ограничения

Стандартен Windows 11 позволява една активна RDP сесия наведнъж и не поддържа едновременен локален и отдалечен вход с един и същи акаунт. За няколко потребителя или паралелни сесии е нужен RDP Wrapper или съответната server лицензна настройка. RemoteApp и smartcard redirection зависят от конфигурацията на Windows хост-а.

## Проверка

Тестовете на живо обхващат пълна сесия, RemoteApp, clipboard, аудио, кирилица и КЕП през smartcard redirection. Локалният КЕП тест на Linux + Firefox е отделен потребителски тест, без промяна в тази функция.
