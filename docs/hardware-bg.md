# Хардуерна оценка

Помощникът чете target машината, а не build компютъра. Probe е read-only: CPU vendor/family, RAM, наличните governors във всички CPU policies, PCI адрес/class/vendor/device и обвързан kernel driver, USB IDs и драйверите на отделните USB интерфейси, Bluetooth HCI/USB клас, DRM KMS модули и дискове. Чете кандидатите чрез `modprobe --resolve-alias`; не ги зарежда в rescue.

Отчетът има `schema_version = 2`, `kernel_version` и `rules_version`.
`pci_devices` съдържа отделни записи по PCI адрес: драйвер, кандидати и до
20 firmware декларации от `modinfo`. Това са сведения от **текущото rescue
ядро**, не обещание за наличност в друго ядро. Firmware декларацията не доказва
наличен файл или успешно зареждане. Недостъпен инструмент се отчита като
неизвестни сведения. Старите JSON отчети без тези полета остават четими и не
получават измислени PCI адреси. TOML схемата и запазените wizard отговори не се
променят.

`hardware_review.devices` свързва съществения PCI интерфейс с основанието,
статус и следващо действие. `pass` тук означава **обвързан драйвер**; функцията
се проверява отделно след инсталация. Bridge/host функции могат правилно да
са без собствен драйвер.

При достъпен kernel log отчита `Direct firmware load ... error -2`. Това е частичен индикатор: липсващ опционален firmware може да има fallback; kernel log може да е недостъпен. Допълнителен unfree firmware не е универсално решение и не включва автоматично NVIDIA proprietary driver.

## Автоматични решения

- Intel/AMD microcode, redistributable firmware и Mesa/DRM са в системния профил.
- Ранните i915/xe/amdgpu/radeon/nouveau модули се вземат от DRM или от активно обвързания PCI GPU драйвер. Не преминаваме от работещ radeon към amdgpu.
- GeForce 9400 GT `10de:0641`, ако е с nouveau: запазваме nouveau и Mesa/KMS автоматично. Историческият proprietary branch е 340; не го избираме автоматично за съвременна офис система. Nixpkgs съдържа и patched legacy код, но това не доказва съвместимост с избрания kernel/Xorg.
- Неоткрит Bluetooth означава изключени BlueZ/Blueman, без излишен въпрос. Това не доказва физическа липса; адаптерът може да е изключен във firmware. По-късно: `devices.bluetooth = true`.
- Динамичен CPU governor според действителния драйвер и наличните политики; performance е доброволен избор, не обещание за ускорение.

## Кога е нужна проверка

Необвързани USB интерфейси, storage/SD/USB контролери, непознат/необвързан GPU, proprietary NVIDIA без проверено съответствие по PCI ID, hybrid GPU/PRIME, необвързани network/audio устройства или firmware грешки се изписват изрично. Те не се „оправят“ с произволен модул. Мрежовите и звуковите драйвери обичайно се зареждат чрез kernel modalias; генерираната NixOS hardware configuration покрива storage/initrd.

Началната оценка не измерва renderer или скорост на приложенията. Диагностиката
по-долу допълва тази оценка след инсталация. Не наричаме конфигурацията
„най-бърза“ само от CPU име и количество RAM. Сравнителни benchmarks,
температурни измервания и автоматичен tuning остават извън M1.

## Диагностика след инсталация

От терминал **в XFCE като офис потребителя**, без sudo:

```sh
nix2office-diagnose
nix2office-diagnose --json
nix2office-diagnose --output "$HOME/diagnose.json"
```

За текуща инсталация, която още няма командата, или от checkout:

```sh
nix run --option builders '' github:cheirekov/nix2office#diagnose
# или от проекта:
nix run --option builders '' .#diagnose -- --json
```

`--output FILE` записва JSON с права `0600`; не замества символна връзка.
Отчетът е валиден и при предупреждения (exit 0); невалидни аргументи или
невъзможен запис връщат грешка. Не променя настройки, не зарежда модули, не
стартира услуги, не пуска звук и не проверява външни сайтове.

| Статус | Значение |
| --- | --- |
| `pass` | Наблюдаваната конкретна проверка е успешна; не гарантира цялото устройство |
| `warning` | Има данни за проблем и следващо действие |
| `unknown` | Липсват данни, инструмент, права или достъп до потребителската сесия |
| `not-applicable` | Проверка за несъществуващо/неприложимо устройство |

Проверяват се PCI и USB interface bindings, OpenGL renderer и software rendering, VA-API
възможности чрез `vainfo`, потребителските PipeWire/WirePlumber услуги,
звуковите sinks/cards, Bluetooth и локални мрежови интерфейси/адреси/маршрути.
VA-API профили не доказват, че браузърът ги използва; VDPAU/други API може да
изискват отделна проверка. Локален default route не доказва достъп до Internet.
При SSH без графичната сесия някои проверки правилно са `unknown`; не копираме
X cookies и не отгатваме DISPLAY. Недостъпен kernel log също е `unknown`.

За звук: избери изход в Настройки → Звук, пусни кратък клип и потвърди чрез
слушане. Наличен HDMI sink, липса на mute или активен PipeWire **не доказват
чуваем звук**. Съхраненият отчет не заменя тази проверка.

## Допълващ пилот с nixos-facter

`#facter` предоставя nixos-facter от **същия текущ nixpkgs pin**; не добавя input
и не включва `hardware.facter.reportPath` или автоматично всички Facter модули.
Версията в текущия pin е 0.4.4. Тя изисква root; обикновената диагностика не
го стартира автоматично. На машината, чийто хардуер сравняваш:

```sh
mkdir -p .nix2office
chmod 700 .nix2office
nix build --option builders '' .#facter --out-link .nix2office/facter-bin
sudo sh -c 'umask 077; exec "$1" --hardware pci,usb --output "$2"' sh \
  "$PWD/.nix2office/facter-bin/bin/nixos-facter" "$PWD/.nix2office/facter.json"
sudo chown "$(id -u):$(id -g)" .nix2office/facter.json
nix run --option builders '' .#diagnose -- --facter-report .nix2office/facter.json
```

Facter може да съдържа серийни номера и други идентификатори. Пази суровия
отчет локално в игнорираната директория; не го добавяй в публичен Git.
Сравняват се наличните PCI факти. Разлика или неподдържана структура означава
проверка/неизвестност, а не автоматична промяна на драйвер. Пилотът не приема,
че всички устройства, видими през единия източник, непременно са отчетени през
другия. Реална проба с root на конкретна машина е отделна от fixture тестовете.

[Пътна карта и критерии за M1](roadmap-bg.md).

Източници: [NVIDIA PCI 0641](https://download.nvidia.com/XFree86/Linux-x86_64/340.108/README/supportedchips.html), [Nouveau power management](https://nouveau.freedesktop.org/PowerManagement.html).
