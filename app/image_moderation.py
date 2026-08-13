"""ИИ-фильтрация изображений: порнография/нагота (NudeNet), насилие (ViT),
свастика (OpenCV) и эвристика крови.

Модуль безопасно деградирует: если библиотеки/модель недоступны, возвращает
"чисто", не ломая публикацию постов.
"""
import threading

# Классы NudeNet, которые считаем запрещённым контентом.
NSFW_CLASSES = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "ANUS_EXPOSED",
}

_nsfw_threshold = 0.5  # достоверность детекции

_lock = threading.Lock()
_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        from nudenet import NudeDetector

        _detector = NudeDetector()
    return _detector


def check_nsfw(image_path, threshold=_nsfw_threshold):
    """Возвращает (flag, reasons). flag=True если найден откровенный контент."""
    try:
        with _lock:
            detections = _get_detector().detect(str(image_path))
    except Exception:
        return False, []
    reasons = []
    for det in detections:
        cls = det.get("class") or det.get("label") or ""
        score = float(det.get("score", 0) or 0)
        if cls in NSFW_CLASSES and score >= threshold:
            reasons.append(
                f"обнаружен откровенный контент ({cls}, достоверность {score:.0%})"
            )
    return len(reasons) > 0, reasons


def _build_swastika_templates():
    """Генерирует эталоны свастики (8 поворотов + зеркальный вариант)."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return []

    def make(side=140, thickness=14, arm=32, hook=32):
        img = np.full((side, side), 255, np.uint8)
        c = side // 2
        # центральный крест
        cv2.rectangle(img, (c - thickness // 2, c - arm), (c + thickness // 2, c + arm), 0, -1)
        cv2.rectangle(img, (c - arm, c - thickness // 2), (c + arm, c + thickness // 2), 0, -1)
        # крючки по часовой (卐)
        cv2.rectangle(img, (c - arm, c - arm), (c, c - arm + thickness), 0, -1)           # вверх — влево
        cv2.rectangle(img, (c - arm, c - arm), (c - arm + thickness, c), 0, -1)           # влево — вверх
        cv2.rectangle(img, (c, c + arm - thickness), (c + arm, c + arm), 0, -1)           # вниз — вправо
        cv2.rectangle(img, (c + arm - thickness, c), (c + arm, c + arm), 0, -1)           # вправо — вниз
        return img

    base = make()
    variants = [base, cv2.flip(base, 1)]  # 卐 и 卍
    templates = []
    for v in variants:
        for angle in range(0, 360, 45):
            M = cv2.getRotationMatrix2D((70, 70), angle, 1.0)
            rot = cv2.warpAffine(v, M, (140, 140), borderValue=255)
            templates.append(rot)
    return templates


_sw_templates = None


def _get_sw_templates():
    global _sw_templates
    if _sw_templates is None:
        _sw_templates = _build_swastika_templates()
    return _sw_templates


def check_swastika(image_path, threshold=0.60):
    """Возвращает (flag, reasons). flag=True если найдена свастика."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return False, []

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return False, []
    templates = _get_sw_templates()
    if not templates:
        return False, []

    best = 0.0
    for scale in (0.35, 0.5, 0.7, 1.0):
        h = int(img.shape[0] * scale)
        if h < 80:
            continue
        im = cv2.resize(img, (int(img.shape[1] * h / img.shape[0]), h))
        for t in templates:
            if t.shape[0] > im.shape[0] or t.shape[1] > im.shape[1]:
                continue
            res = cv2.matchTemplate(im, t, cv2.TM_CCOEFF_NORMED)
            if res.size:
                _, maxv, _, _ = cv2.minMaxLoc(res)
                if maxv > best:
                    best = float(maxv)

    if best >= threshold:
        return True, [f"обнаружена свастика (сходство {best:.0%})"]
    return False, []


_VIOLENCE_MODEL_PATH = "/opt/eventsmap/violence_int8.onnx"
_violence_session = None
_violence_lock = threading.Lock()
_VIOLENCE_VIOLENT_INDEX = 1  # 0 = non_violence, 1 = violence


def _get_violence_session():
    global _violence_session
    if _violence_session is None:
        import onnxruntime as ort

        _violence_session = ort.InferenceSession(
            _VIOLENCE_MODEL_PATH,
            providers=["CPUExecutionProvider"],
        )
    return _violence_session


def check_violence(image_path, threshold=0.5):
    """Детекция насилия/жёсткого контента через ViT-модель.

    Модель обучена на реальных сценах насилия и распознаёт содержание кадра,
    а не цвет — перекраска/фильтры не обходят её.
    """
    import os

    if not os.path.exists(_VIOLENCE_MODEL_PATH):
        return False, []
    try:
        import cv2
        import numpy as np

        img = cv2.imread(str(image_path))
        if img is None:
            return False, []
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (224, 224), interpolation=cv2.INTER_LINEAR)
        x = img.astype(np.float32) / 255.0
        x = (x - 0.5) / 0.5
        x = np.transpose(x, (2, 0, 1))[None]  # 1,3,224,224
        with _violence_lock:
            session = _get_violence_session()
            logits = session.run(None, {session.get_inputs()[0].name: x})[0]
        probs = np.exp(logits[0] - np.max(logits[0]))
        probs = probs / probs.sum()
        score = float(probs[_VIOLENCE_VIOLENT_INDEX])
        if score >= threshold:
            return True, [f"обнаружено насилие/жёсткий контент (ИИ, уверенность {score:.0%})"]
        return False, []
    except Exception:
        return False, []


def check_gore(image_path):
    """Эвристика жёсткого контента: большие области крови/ран.

    Детектирует насыщенно-красные области (цвет крови) и размытые красные
    участки, покрывающие заметную часть изображения. Ложные срабатывания
    возможны на красно-оранжевых фото, поэтому порог консервативный.
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        return False, []

    img = cv2.imread(str(image_path))
    if img is None:
        return False, []
    h, w = img.shape[:2]
    if h < 40 or w < 40:
        return False, []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # красный в HSV: два диапазона (0..10 и 170..180)
    lower1 = np.array([0, 90, 60], dtype=np.uint8)
    upper1 = np.array([12, 255, 255], dtype=np.uint8)
    lower2 = np.array([168, 90, 60], dtype=np.uint8)
    upper2 = np.array([180, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower1, upper1) | cv2.inRange(hsv, lower2, upper2)
    area = int(mask.sum() / 255)
    total = h * w
    ratio = area / total
    if ratio < 0.18:
        return False, []
    # размер связных областей крови должен быть существенным
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    biggest = 0
    for i in range(1, n):
        if stats[i][4] > biggest:
            biggest = int(stats[i][4])
    if biggest < total * 0.08:
        return False, []
    return True, [f"обнаружен жёсткий контент (кровь/раны, {ratio:.0%} кадра)"]


def check_image(image_path):
    """Полная проверка одного изображения. Возвращает (flag, reasons)."""
    reasons = []
    nsfw_flag, nsfw_reasons = check_nsfw(image_path)
    reasons.extend(nsfw_reasons)
    sw_flag, sw_reasons = check_swastika(image_path)
    reasons.extend(sw_reasons)
    gore_flag, gore_reasons = check_gore(image_path)
    reasons.extend(gore_reasons)
    viol_flag, viol_reasons = check_violence(image_path)
    reasons.extend(viol_reasons)
    return (len(reasons) > 0), reasons
