# RustDesk отдалечена поддръжка

Изборът е в конфигуратора и `#maintain --edit`: изключено (`off`), потвърждение с клик (`consent`) или постоянна парола без присъствие (`unattended`). При включена поддръжка системната услуга `rustdesk.service` стартира като root с `--service` още при boot, след LightDM и услугите за потребителски сесии. RustDesk следи активната сесия и управлява своя `--server` и tray. Предишната отделна потребителска услуга `nix2office-rustdesk` е премахната, за да няма втори управляван daemon/tray.

```toml
[remote_support]
mode = "consent" # off, consent, unattended
id_server = "rustdesk.example.org"
relay_server = "rustdesk.example.org"
public_key = "PUBLIC_BASE64_SERVER_KEY"
```

При `unattended` поддръжката може да се свърже с login екрана след рестарт, без предварителен вход в XFCE. Все още са нужни работеща мрежа, достъпен hbbs/hbbr и стартирал LightDM/Xorg. RustDesk не отключва криптиран диск в initrd, не показва firmware/bootloader екрани и не заобикаля паролата за вход в Linux. При `consent` остава задължително локално потвърждение; няма автоматично разрешение преди login. Не разчитайте, че прозорецът за потвърждение ще работи в ограничената greeter сесия. За дистанционно възстановяване след reboot използвайте изрично избрания режим `unattended`.

## Парола и идентичност

Парола не се въвежда в TOML. При `unattended` помощникът я иска скрито два пъти (12–128 знака, без LF/CR/NUL), криптира я в частния `rustdesk.yaml` за същите host/operator age ключове и я предоставя чрез sops-nix. Системната услуга чете runtime файла чрез systemd `LoadCredential`. Паролата не е аргумент на процес, environment variable или съдържание в Nix store. Между подготвящия root процес и помощните процеси за потребителите се предава по stdin pipe; грешките не отпечатват credentials.

Преди daemon старта се подготвят `RustDesk.toml` и `RustDesk2.toml` в `/root/.config/rustdesk`, в `~/.config/rustdesk` на офис потребителя и в `/var/lib/lightdm/.config/rustdesk` за greeter. Root конфигурацията е водеща. Ако още няма root идентичност, се запазва съществуващата идентичност на офис потребителя; при чиста инсталация RustDesk `--get-id` генерира ID, а libsodium създава същия Ed25519 формат ключове, използван от RustDesk. ID/enc_id, signing key pair, salt и потвържденията за ключове се подготвят еднакво за трите акаунта. Това избягва смяна на управляваната идентичност при преминаване от login екрана към XFCE и изчакване на първата upstream IPC синхронизация.

Същите сървъри, публичен ключ и режим се прилагат и за трите акаунта преди старта. При `consent` постоянната парола се изчиства навсякъде и се избират `approve-mode=click` и временна парола; при `unattended` се избират само постоянна парола и `approve-mode=password`. Другите настройки се запазват. Подготовката отказва старт при липсваща/невалидна парола или опасни конфигурационни пътища, вместо да пусне daemon с непълна подготовка.

Директориите за RustDesk са с права 0700, файловете — 0600, със собственика на съответния акаунт. Root процесът не пише с root права в потребителски home директории: помощните процеси сменят UID/GID и изчистват допълнителните групи. Symlink в конфигурационния път, symlink/hardlink/non-regular файл или чужд собственик на конфигурационния файл водят до отказ. При такава грешка администраторът трябва да провери собствеността и пътя, без да разхлабва правата.

Постоянната парола и частната идентичност присъстват и в защитените конфигурации на офис и greeter акаунтите, защото upstream server се изпълнява в активния акаунт и синхронизира конфигурацията с root по IPC. Самият RustDesk преобразува паролата в своя формат при зареждане. Това не защитава паролата от компрометиран офис/greeter акаунт. Промените през RustDesk UI могат да се синхронизират обратно към root; настройките се прилагат отново при рестарт на системната услуга, не са постоянна забрана за локална промяна.

За подмяна на паролата преименувайте частния криптиран `rustdesk.yaml` и повторете подготовката; запазете старото копие до успешен build. След инсталиране/дешифриране на новия secret изпълнете `sudo systemctl restart rustdesk`. Смяна само на съдържанието на secret при същия `LoadCredential` път не гарантира автоматичен рестарт. Смяна на режим/сървър също се прилага при рестарт на услугата; не е необходим вход в XFCE.

## LightDM/Xorg и проверка

Тази интеграция изисква офис конфигурацията с LightDM и Xorg. Запазва се cookie автентикацията на X11. LightDM използва `user-authority-in-system-dir=false`, така че RustDesk 1.4.5 може да използва своя fallback към `~/.Xauthority` на активния акаунт, включително `/var/lib/lightdm/.Xauthority`. Не се използват `xhost +`, изключване на X11 access control или фиксиран `DISPLAY=:0`. Upstream dispatcher избира server акаунта според активната logind сесия: при LightDM greeter това може да е `lightdm`, а след login — офис потребителят; самият dispatcher остава root.

След инсталацията проверете:

1. `systemctl status rustdesk` и `journalctl -u rustdesk -b` — успешна подготовка и един root dispatcher `--service`.
2. От отделен клиент през реалния hbbs/hbbr: входяща връзка при `unattended` още на LightDM екрана след reboot, после вход в XFCE, logout и повторна връзка със същия RustDesk ID.
3. Невалидна парола се отхвърля; след преминаване към `consent` старата постоянна парола не предоставя достъп и остава нужно потвърждение.
4. При `off` след активиране няма управлявана системна или потребителска услуга и RustDesk пакетът е премахнат от тази интеграция.

`off` не изтрива запазените частни конфигурации, upstream autostart файлове или самостоятелни инсталации. За връщане назад възстановете предишното поколение/режим и рестартирайте управляваната услуга. В рамките на тази промяна са проверени подготовката и Nix оценяването; реални входящи връзки, login/logout и reboot на целевия компютър остават приемателен тест след инсталацията.

Не стартираме hbbs/hbbr на офис машината и не отваряме входящи server портове. hbbs е ID сървърът, hbbr е relay; HTTP/SOCKS proxy е друга настройка.

Първични източници: [systemd unit на RustDesk 1.4.5](https://github.com/rustdesk/rustdesk/blob/1.4.5/res/rustdesk.service), [Linux dispatcher и Xauthority discovery](https://github.com/rustdesk/rustdesk/blob/1.4.5/src/platform/linux.rs), [server/tray и CLI](https://github.com/rustdesk/rustdesk/blob/1.4.5/src/core_main.rs), [root/user IPC синхронизация](https://github.com/rustdesk/rustdesk/blob/1.4.5/src/server.rs), [config paths и identity формат в точния hbb_common submodule](https://github.com/rustdesk/hbb_common/blob/073403edbf1fffcb3acfe8cbe7582ee873b23398/src/config.rs), [режими за парола](https://github.com/rustdesk/hbb_common/blob/073403edbf1fffcb3acfe8cbe7582ee873b23398/src/password_security.rs), [LightDM authority избор](https://github.com/canonical/lightdm/blob/main/src/x-server.c) и [authority файл](https://github.com/canonical/lightdm/blob/main/src/session.c), [NixOS LightDM при project pin](https://github.com/NixOS/nixpkgs/blob/718f670e845328e9c2cecdd832835712b2cbd065/nixos/modules/services/x11/display-managers/lightdm.nix), [официална клиентска конфигурация](https://rustdesk.com/docs/en/self-host/client-configuration/).
