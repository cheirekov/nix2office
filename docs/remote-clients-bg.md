# Клиенти за отдалечени работни места и приложения

Проверено по документацията на доставчиците и проектите на 26 ноември 2026 г.
Списъкът обхваща услугите от пътната карта и приложенията за най-близките
протоколи и сценарии. Поддръжка на Linux от доставчика и работещ пакет в
NixOS са отделни критерии. За корпоративни услуги определящи са и настройките
на организацията, лицензът, достъпът до конкретната среда и периферията.

## Управлявани услуги

| Услуга | Достъп от Linux | Значение за Nix2office |
| --- | --- | --- |
| AWS WorkSpaces Personal | Официален нативен DCV клиент за Ubuntu и официален Web Access | Опция в Thin/Kiosk чрез `aws-workspaces`. Нужни са назначен WorkSpace и разрешен тип клиент за директорията. [Клиенти](https://docs.aws.amazon.com/workspaces/latest/userguide/amazon-workspaces-clients.html) |
| AWS WorkSpaces Pools | Официален Web Access. Таблицата на AWS изключва нативния Linux клиент за Pools | HTTPS профил при налична среда. [Съвместимост](https://docs.aws.amazon.com/workspaces/latest/userguide/supported-features-wsp.html) |
| AWS WorkSpaces Applications (AppStream 2.0) | Официален HTML5 клиент. Нативни приложения за Windows и macOS | HTTPS профил за публикувани приложения. [Браузъри](https://docs.aws.amazon.com/appstream2/latest/developerguide/system-requirements-considerations-web-browser-admin.html) · [Функции](https://docs.aws.amazon.com/appstream2/latest/developerguide/client-features.html) |
| Azure Virtual Desktop, Windows 365 и Microsoft Dev Box | Официален Windows App в браузър. Налични са партньорски thin клиенти за AVD, например IGEL. Microsoft не предлага нативен Windows App за обща Linux дистрибуция | HTTPS профил за пилот. FreeRDP описва общностен AVD път с `.rdpw`, който изисква отделна проверка с tenant и MFA. [Windows App](https://learn.microsoft.com/en-us/windows-app/overview) · [Партньори](https://learn.microsoft.com/en-us/azure/virtual-desktop/thin-clients) · [FreeRDP AVD](https://github.com/FreeRDP/FreeRDP/wiki/FAQ#connect-to-azure-virtual-desktop-avd) |
| Google Cloud Cameyo | Официален браузърен достъп до Windows приложения | HTTPS профил за публикувани приложения. [Google Cloud](https://cloud.google.com/solutions/virtual-desktops) |
| Google Compute Engine, Windows VM | Обикновен RDP клиент, с частна мрежа или TCP тунел през `gcloud` и IAP. Chrome Remote Desktop е отделна официална браузърна услуга с агент на хоста | FreeRDP през подходящ транспорт или отделен HTTPS пилот с Chrome Remote Desktop. [Windows VM](https://docs.cloud.google.com/compute/docs/instances/connecting-to-windows) · [IAP](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding) |
| Dizzion Frame | Официален браузърен достъп до приложения и десктопи | HTTPS профил при налична среда. [Google Cloud партньори](https://cloud.google.com/solutions/virtual-desktops) |
| Citrix Virtual Apps and Desktops / DaaS | Официални Citrix Workspace app за Linux и HTML5 клиент | Кандидат за опционален нативен профил със съвместим Citrix Store. [Клиенти и версии](https://docs.citrix.com/us/en/client-app-management/client-app-considerations/workspace-app.html) |
| Omnissa Horizon | Официален Horizon Client for Linux | Кандидат за опционален нативен профил при наличен Horizon broker. [Изисквания](https://docs.omnissa.com/HorizonClientLinuxGuide-V2512/SystemRequirements/) |
| Parallels RAS | Официален Parallels Client for Linux | Кандидат при наличен RAS. [Ръководство](https://docs.parallels.com/landing/ras-linux-client-guide) |
| Leostream | Официален Leostream Connect за Linux. Broker-ът може да стартира отделни клиенти според протокола | Оценка с конкретен broker и избран протокол. [Leostream Connect](https://docs.leostream.com/v2024/leostream_connect.pdf) |
| HP Anyware | Официален Linux PCoIP клиент | Самостоятелен кандидат при налична Anyware среда и поддържани версии. [Linux клиент](https://anyware.hp.com/documentation/components/software-client-for-linux/release-notes) |

## Самостоятелни хостове, шлюзове и общностни клиенти

| Клиент или шлюз | Какво обслужва | Източник |
| --- | --- | --- |
| FreeRDP и Remmina | Общностни Linux клиенти за RDP. Remmina дава графично управление на връзки и други протоколи. FreeRDP е текущият RDP клиент на киоска | [FreeRDP](https://github.com/FreeRDP/FreeRDP) · [Remmina](https://remmina.org/) |
| WinApps | Общностна интеграция на Windows приложения в локалния Linux desktop чрез FreeRDP и RemoteApp | [WinApps](https://github.com/winapps-org/winapps) |
| Amazon DCV | Официален нативен Linux клиент и браузърен клиент за собствен DCV сървър, например на EC2. Услугата използва отделна конфигурация от WorkSpaces | [DCV Linux клиент](https://docs.aws.amazon.com/dcv/latest/userguide/client-linux.html) |
| NoMachine | Официален Linux клиент за NoMachine хостове и сървъри | [NoMachine Enterprise Client](https://www.nomachine.com/enterprise/enterprise-desktop-products/enterprise-client) |
| ThinLinc и X2Go | ThinLinc има нативен Linux и HTML5 клиент за отдалечен Linux desktop. X2Go е общностен проект с нативен клиент за X2Go сървър | [ThinLinc](https://www.cendio.com/thinlinc/docs/install/) · [X2Go](https://wiki.x2go.org/doku.php/doc:installation:x2goclient) |
| Apache Guacamole и Kasm Workspaces | Браузърни шлюзове за собствени отдалечени ресурси. Guacamole приема RDP, VNC и SSH. Kasm предоставя и браузърни работни сесии | [Guacamole](https://guacamole.apache.org/) · [Kasm](https://docs.kasm.com/docs/install/system_requirements) |
| TigerVNC и virt-viewer | Общностни Linux клиенти съответно за VNC и за SPICE конзола на VM | [TigerVNC](https://github.com/TigerVNC/tigervnc) · [SPICE](https://www.spice-space.org/download.html) |
| RustDesk | Избираем клиент в Thin/Kiosk и Hybrid. За входяща поддръжка проектът използва отделна системна услуга с LightDM/Xorg. Хардуерният H.264/H.265 зависи от GPU и драйвера | [Linux клиент](https://rustdesk.com/docs/en/client/linux/) · [Кодеци](https://rustdesk.com/docs/en/self-host/client-configuration/advanced-settings/#codec-preference) |
| AnyDesk | Избираем графичен клиент в Thin/Kiosk и Hybrid. Пакетът в текущия pin използва X11, GTK и PulseAudio библиотеки. NixOS е извън официалния списък на доставчика | [Linux съвместимост](https://support.anydesk.com/anydesk-for-linux-raspberry-pi) |
| RealVNC Viewer | Избираем клиент в Thin/Kiosk и Hybrid за VNC сървъри. Фиксираният Linux пакет е за x86_64 и използва X11 библиотеки | [RealVNC Viewer](https://help.realvnc.com/hc/en-us/articles/360002252798-Supported-Platforms-for-RealVNC-Connect-v7) |
| GNOME Connections | Избираем клиент в Thin/Kiosk и Hybrid за прости RDP/VNC връзки. Фиксираният пакет използва GTK3, libhandy и libsecret. Пренасочването и клавиатурата се оценяват за всеки клиент поотделно | [GNOME Connections](https://apps.gnome.org/Connections/) |
| Moonlight | Избираем клиент в Thin/Kiosk и Hybrid за десктоп и видео стрийминг. Изисква съвместим хост, например Sunshine. Фиксираният пакет включва Qt, FFmpeg, VA-API и VDPAU. Плавността зависи от кодека, драйвера и хардуера на клиента и хоста | [Moonlight Qt](https://github.com/moonlight-stream/moonlight-qt) |

### Още варианти за пилота

| Вариант | Как се включва и какво е нужно | Източник |
| --- | --- | --- |
| Splashtop Business | Възможен HTTPS профил при поддържан абонамент, браузър и Streamer на отдалечения хост. Доставчикът предлага и Linux приложение. За него няма установен пакет в текущия pin | [Web App](https://support-splashtopbusiness.splashtop.com/hc/en-us/articles/4630897874203-Web-App) · [Linux клиент](https://support-splashtopbusiness.splashtop.com/hc/en-us/articles/115001403303-Does-Splashtop-support-Linux) |
| DWService и MeshCentral | Възможни HTTPS профили при инсталиран агент на отдалечения хост. MeshCentral изисква и собствен или предоставен сървър | [DWService](https://docs.dwservice.net/docs/site/dwservice-installation/how-do-i-use-the-service/) · [MeshCentral](https://docs.meshcentral.com/) |
| TeamViewer | Има NixOS модул. Той стартира системен демон, затова режимът му на работа трябва да се уточни преди добавяне в магьосника | [Linux поддръжка](https://www.teamviewer.com/en/global/support/knowledge-base/teamviewer-remote/download-and-installation/supported-operating-systems-for-teamviewer-remote/) |
| HopToDesk и Devolutions Remote Desktop Manager | Доставчиците публикуват Linux инсталатори. Няма установен пакет в текущия pin. Отделни кандидати за пакетиране при наличен сценарий | [HopToDesk](https://www.hoptodesk.com/download) · [Devolutions](https://devolutions.net/remote-desktop-manager/download/) |
| KDE KRDC | Пакет в текущия pin за RDP и VNC с KDE/Qt зависимости. Покритие, сходно с това на GNOME Connections и Remmina | [KRDC](https://apps.kde.org/krdc/) |
| Parsec | Linux клиент за стрийминг от съвместим Parsec хост. Фиксираният пакет изтегля стара версия от Internet Archive. Подходящ за отделна оценка след проверка на източника и съвместимостта | [Parsec за Linux](https://support.parsec.app/hc/en-us/articles/32381494397332-Parsec-App-for-Linux) |

За Thin/Kiosk първият пилот е WorkSpaces Personal DCV. На един и същ
WorkSpace сравняваме Web Access и нативния клиент по вход, кирилица, звук,
отзивчивост, памет и файлов трансфер. AWS изброява локален печат за Linux
клиента. USB и CAC/PIV пренасочване липсват в таблицата както за Linux
клиента, така и за браузъра. Функции за MFA при вход и КЕП вътре в
отдалеченото приложение се проверяват поотделно.
[Функции на WorkSpaces DCV](https://docs.aws.amazon.com/workspaces/latest/userguide/supported-features-wsp.html)

При Hybrid същите видове връзки са подходящи за избираеми стартери от
работния плот. Всеки нов нативен клиент има смисъл при налична целева
среда, проверени лиценз и зависимости и потвърден вход от NixOS.
