# Хардуерна оценка

Помощникът чете target машината, а не build компютъра. Probe е read-only: CPU vendor/family, RAM, наличните governors във всички CPU policies, PCI class/vendor/device и обвързан kernel driver, USB IDs и драйверите на отделните USB интерфейси, Bluetooth HCI/USB клас, DRM KMS модули и дискове. За необвързани PCI устройства чете кандидатите чрез `modprobe --resolve-alias`; не ги зарежда в rescue.

При достъпен kernel log отчита `Direct firmware load ... error -2`. Това е частичен индикатор: липсващ опционален firmware може да има fallback; kernel log може да е недостъпен. Допълнителен unfree firmware не е универсално решение и не включва автоматично NVIDIA proprietary driver.

## Автоматични решения

- Intel/AMD microcode, redistributable firmware и Mesa/DRM са в системния профил.
- Ранните i915/xe/amdgpu/radeon/nouveau модули се вземат от DRM или от активно обвързания PCI GPU драйвер. Не преминаваме от работещ radeon към amdgpu.
- GeForce 9400 GT `10de:0641`, ако е с nouveau: запазваме nouveau и Mesa/KMS автоматично. Историческият proprietary branch е 340; не го избираме автоматично за съвременна офис система. Nixpkgs съдържа и patched legacy код, но това не доказва съвместимост с избрания kernel/Xorg.
- Неоткрит Bluetooth означава изключени BlueZ/Blueman, без излишен въпрос. Това не доказва физическа липса; адаптерът може да е изключен във firmware. По-късно: `devices.bluetooth = true`.
- Динамичен CPU governor според действителния драйвер и наличните политики; performance е доброволен избор, не обещание за ускорение.

## Кога е нужна проверка

Необвързани USB интерфейси, storage/SD/USB контролери, непознат/необвързан GPU, proprietary NVIDIA без проверено съответствие по PCI ID, hybrid GPU/PRIME, необвързани network/audio устройства или firmware грешки се изписват изрично. Те не се „оправят“ с произволен модул. Мрежовите и звуковите драйвери обичайно се зареждат чрез kernel modalias; генерираната NixOS hardware configuration покрива storage/initrd.

Оценката не измерва OpenGL renderer, software rendering, VA-API/VDPAU, температурно ограничаване или реално време за стартиране на офис приложения. След инсталация тези проверки могат да потвърдят ускорението и да насочат корекция. Не наричаме конфигурацията „най-бърза“ само от CPU име и количество RAM.

Източници: [NVIDIA PCI 0641](https://download.nvidia.com/XFree86/Linux-x86_64/340.108/README/supportedchips.html), [Nouveau power management](https://nouveau.freedesktop.org/PowerManagement.html).
