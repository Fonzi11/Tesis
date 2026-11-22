using System.Collections;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.XR;

/// <summary>
/// Recorrido de demostración: repite despacio, sobre la app real, la misma
/// secuencia de gestos que las simulaciones automáticas, con manos simuladas
/// visibles (esferas azul = izquierda, naranja = derecha; se agrandan al hacer
/// pinza) y rótulos en pantalla. Pensado para mostrar el sistema sin visor.
///
/// Se activa con el argumento <c>-atlas-demo</c> (Editor o reproductor) o,
/// en el Editor, con el menú ATLAS/MR/Reproducir demostración.
/// <c>-atlas-capturas carpeta</c> guarda una captura por paso en la primera
/// vuelta. Espacio pausa/reanuda; los controles de teclado siguen activos.
/// </summary>
public sealed class NeuroHubDemoTour : MonoBehaviour
{
    public const string Flag = "-atlas-demo";
    public const string EditorPrefKey = "neurohub.demo";

    private NeuroHubStudyLoader loader;
    private NeuroHubGestureController gestures;
    private NeuroHubSimulatedHandSource hands;
    private Transform leftBall, rightBall;
    private string step = "Iniciando…";
    private string captureDir;
    private int captureCount;
    private bool paused;
    private int studyNumber, studyCount;
    private float fps = 60f;
    private GUIStyle panel, title, caption, small;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Boot()
    {
        bool requested = System.Environment.GetCommandLineArgs().Contains(Flag);
#if UNITY_EDITOR
        requested |= PlayerPrefs.GetInt(EditorPrefKey, 0) == 1;
#endif
        if (requested) new GameObject("ATLAS_Demostracion").AddComponent<NeuroHubDemoTour>();
    }

    private IEnumerator Start()
    {
        loader = FindObjectOfType<NeuroHubStudyLoader>();
        gestures = FindObjectOfType<NeuroHubGestureController>();
        if (loader == null || gestures == null)
        {
            step = "La escena no tiene el cargador o el controlador de gestos";
            yield break;
        }
        captureDir = ArgValue("-atlas-capturas");
        if (!string.IsNullOrEmpty(captureDir)) Directory.CreateDirectory(captureDir);

        hands = gestures.gameObject.AddComponent<NeuroHubSimulatedHandSource>();
        NeuroHubHandSource[] sources = FindObjectsOfType<NeuroHubHandSource>()
            .Where(s => s != hands).Append(hands).ToArray();
        gestures.Configure(loader.StudyRoot, loader, sources);
        leftBall = MakeBall("Mano_izquierda_simulada", new Color(0.25f, 0.6f, 1f));
        rightBall = MakeBall("Mano_derecha_simulada", new Color(1f, 0.55f, 0.15f));

        string[] studies = loader.StudyIndex.Length > 0 ? loader.StudyIndex : new[] { loader.studyId };
        studyCount = studies.Length;
        yield return null;  // deja arrancar la carga inicial del propio cargador
        for (int lap = 0; ; lap++)
        {
            for (int i = 0; i < studies.Length; i++)
            {
                studyNumber = i + 1;
                step = "Cargando " + studies[i] + "…";
                while (loader.IsLoading) yield return null;
                if (loader.studyId != studies[i] || loader.LoadedModels.Count == 0)
                    yield return loader.LoadStudy(studies[i]);
                gestures.ResetTransform();
                yield return Tour(studies[i], lap == 0);
            }
        }
    }

    private IEnumerator Tour(string study, bool capture)
    {
        Transform root = loader.StudyRoot;
        Vector3 c = root.position;
        Vector3 lHome = c + new Vector3(-0.11f, -0.04f, -0.12f);
        Vector3 rHome = c + new Vector3(0.11f, -0.04f, -0.12f);

        step = "Vista general: modelo translúcido a escala real";
        yield return Wait(0.6f);
        if (capture) yield return Capture(study, "vista_general");
        yield return Animate(3.5f, t => root.Rotate(Vector3.up, 50f * Time.unscaledDeltaTime, Space.World));
        if (capture) yield return Capture(study, "vista_girada");
        gestures.ResetTransform();

        step = "Pinza con una mano: trasladar (10 cm a la derecha)";
        yield return Pinch(false, rHome, rHome + Vector3.right * 0.10f, 1.6f);
        if (capture) yield return Capture(study, "pinza_trasladar");
        yield return Pinch(false, rHome + Vector3.right * 0.10f, rHome, 1.2f);

        step = "Pinza con dos manos: escalar ×1,5";
        yield return TwoHands(lHome, rHome, c, 1.5f, 0f, 2f);
        if (capture) yield return Capture(study, "dos_manos_escalar");
        yield return TwoHands(lHome + (lHome - c) * 0.5f, rHome + (rHome - c) * 0.5f, c, 1f / 1.5f, 0f, 1.5f);

        step = "Pinza con dos manos: rotar 45°";
        yield return TwoHands(lHome, rHome, c, 1f, 45f, 2f);
        if (capture) yield return Capture(study, "dos_manos_rotar");
        gestures.ResetTransform();

        int layers = loader.GroupsPresent().Count(g => System.Array.IndexOf(NeuroHubStudyLoader.PeelOrder, g) >= 0);
        for (int k = 0; k < layers; k++)
        {
            string next = NeuroHubStudyLoader.PeelOrder.FirstOrDefault(g =>
                loader.GroupsPresent().Contains(g) && loader.IsGroupVisible(g));
            step = $"Toque mano izquierda: pelar capa ({k + 1}/{layers}) — oculta «{Pretty(next)}»";
            yield return Tap(true, lHome);
            yield return Wait(1.3f);
            if (capture) yield return Capture(study, $"pelar_{k + 1}_{next}");
        }
        step = $"Sólo la lesión ({loader.Manifest?.lesionType}) — girando";
        yield return Animate(3f, t => root.Rotate(Vector3.up, 60f * Time.unscaledDeltaTime, Space.World));
        if (capture) yield return Capture(study, "solo_lesion");
        loader.ShowAllLayers();
        gestures.ResetTransform();

        step = "Toque mano derecha: despiece alrededor de la lesión";
        yield return Tap(false, rHome);
        yield return Wait(1f);
        yield return Animate(3f, t => root.Rotate(Vector3.up, 40f * Time.unscaledDeltaTime, Space.World));
        if (capture) yield return Capture(study, "despiece");
        yield return Tap(false, rHome);
        yield return Wait(1f);

        step = "Pinza breve con las dos manos: restablecer";
        root.Rotate(Vector3.up, 30f, Space.World);
        root.position += Vector3.right * 0.05f;
        yield return Wait(0.8f);
        yield return TwoHandTap(lHome, rHome);
        yield return Wait(1.2f);
        if (capture) yield return Capture(study, "restablecido");
    }

    // --------------------------------------------------------------- manos
    private IEnumerator Pinch(bool left, Vector3 from, Vector3 to, float seconds)
    {
        SetHand(left, from, false);
        yield return Wait(0.35f);
        yield return Animate(seconds, t => SetHand(left, Vector3.Lerp(from, to, Smooth(t)), true));
        SetHand(left, to, false);
        yield return Wait(0.4f);
        ClearHands();
    }

    private IEnumerator Tap(bool left, Vector3 at)
    {
        SetHand(left, at, false);
        yield return Wait(0.3f);
        SetHand(left, at, true);
        yield return WaitReal(0.15f);
        SetHand(left, at, false);
        yield return Wait(0.3f);
        ClearHands();
    }

    private IEnumerator TwoHands(Vector3 l0, Vector3 r0, Vector3 center, float scale, float yawDeg, float seconds)
    {
        hands.left = NeuroHubSimulatedHandSource.Hand(l0, false);
        hands.right = NeuroHubSimulatedHandSource.Hand(r0, false);
        yield return Wait(0.35f);
        yield return Animate(seconds, t =>
        {
            float s = Mathf.Lerp(1f, scale, Smooth(t));
            Quaternion q = Quaternion.AngleAxis(yawDeg * Smooth(t), Vector3.up);
            hands.left = NeuroHubSimulatedHandSource.Hand(center + q * ((l0 - center) * s), true);
            hands.right = NeuroHubSimulatedHandSource.Hand(center + q * ((r0 - center) * s), true);
        });
        hands.left.pinching = hands.right.pinching = false;
        yield return Wait(0.4f);
        ClearHands();
    }

    private IEnumerator TwoHandTap(Vector3 l, Vector3 r)
    {
        hands.left = NeuroHubSimulatedHandSource.Hand(l, false);
        hands.right = NeuroHubSimulatedHandSource.Hand(r, false);
        yield return Wait(0.3f);
        hands.left.pinching = hands.right.pinching = true;
        yield return WaitReal(0.15f);
        hands.left.pinching = hands.right.pinching = false;
        yield return Wait(0.3f);
        ClearHands();
    }

    private void SetHand(bool left, Vector3 p, bool pinching)
    {
        if (left) { hands.left = NeuroHubSimulatedHandSource.Hand(p, pinching); hands.right = default; }
        else { hands.right = NeuroHubSimulatedHandSource.Hand(p, pinching); hands.left = default; }
    }

    private void ClearHands() => hands.left = hands.right = default;

    private void LateUpdate()
    {
        if (hands == null) return;
        UpdateBall(leftBall, hands.left);
        UpdateBall(rightBall, hands.right);
        fps = Mathf.Lerp(fps, 1f / Mathf.Max(Time.unscaledDeltaTime, 1e-4f), 0.05f);
        if (UnityEngine.InputSystem.Keyboard.current?.spaceKey.wasPressedThisFrame == true) paused = !paused;
    }

    private static void UpdateBall(Transform ball, NeuroHubHandState h)
    {
        ball.gameObject.SetActive(h.tracked);
        if (!h.tracked) return;
        ball.position = h.pinchPosition;
        ball.localScale = Vector3.one * (h.pinching ? 0.024f : 0.014f);
    }

    private static Transform MakeBall(string name, Color color)
    {
        GameObject go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        go.name = name;
        Destroy(go.GetComponent<Collider>());
        Shader shader = Shader.Find("Universal Render Pipeline/Unlit") ?? Shader.Find("Unlit/Color");
        Material m = new(shader);
        m.SetColor("_BaseColor", color);
        m.color = color;
        go.GetComponent<Renderer>().sharedMaterial = m;
        go.SetActive(false);
        return go.transform;
    }

    // -------------------------------------------------------------- tiempo
    private IEnumerator Animate(float seconds, System.Action<float> frame)
    {
        float t = 0f;
        while (t < seconds)
        {
            if (!paused) { t += Time.unscaledDeltaTime; frame(Mathf.Clamp01(t / seconds)); }
            yield return null;
        }
    }

    private IEnumerator Wait(float seconds) => Animate(seconds, _ => { });

    /// <summary>Espera sin pausa (la duración de un toque debe ser exacta).</summary>
    private static IEnumerator WaitReal(float seconds)
    {
        float end = Time.unscaledTime + seconds;
        while (Time.unscaledTime < end) yield return null;
    }

    private static float Smooth(float t) => t * t * (3f - 2f * t);

    // ------------------------------------------------------------- rótulos
    /// <summary>Guarda el cuadro actual y espera a que se escriba (con su rótulo).</summary>
    private IEnumerator Capture(string study, string what)
    {
        if (string.IsNullOrEmpty(captureDir)) yield break;
        string path = Path.Combine(captureDir, $"{study}_{++captureCount:00}_{what}.png");
        ScreenCapture.CaptureScreenshot(path);
        yield return null;
        yield return null;
    }

    private static string Pretty(string group) => group switch
    {
        "craneo" => "cráneo",
        "corteza" => "corteza cerebral",
        "sustancia_blanca" => "sustancia blanca",
        "cerebelo_tronco" => "cerebelo y tronco",
        "ventriculos" => "ventrículos",
        "profundas" => "núcleos profundos",
        "vasos" => "arterias",
        _ => group ?? "—",
    };

    private void OnGUI()
    {
        float k = Screen.height / 1080f;
        if (panel == null)
        {
            Texture2D bg = new(1, 1);
            bg.SetPixel(0, 0, new Color(0f, 0f, 0f, 0.6f));
            bg.Apply();
            panel = new GUIStyle { normal = { background = bg }, padding = new RectOffset(16, 16, 12, 12) };
            title = new GUIStyle(GUI.skin.label) { fontStyle = FontStyle.Bold, normal = { textColor = Color.white } };
            caption = new GUIStyle(GUI.skin.label) { alignment = TextAnchor.MiddleCenter, fontStyle = FontStyle.Bold,
                normal = { textColor = new Color(1f, 0.85f, 0.4f) }, wordWrap = true };
            small = new GUIStyle(GUI.skin.label) { normal = { textColor = new Color(0.85f, 0.88f, 0.92f) }, richText = true };
        }
        title.fontSize = Mathf.RoundToInt(26 * k);
        caption.fontSize = Mathf.RoundToInt(28 * k);
        small.fontSize = Mathf.RoundToInt(19 * k);

        NeuroHubStudyManifest m = loader != null ? loader.Manifest : null;
        int tris = m?.models?.Sum(x => x.triangles) ?? 0;
        GUILayout.BeginArea(new Rect(20 * k, 20 * k, 560 * k, 260 * k), panel);
        GUILayout.Label("ATLAS MR — simulación de gestos", title);
        GUILayout.Label($"Estudio {studyNumber}/{studyCount}: <b>{m?.studyId ?? "…"}</b>", small);
        GUILayout.Label($"Lesión: <b>{m?.lesionType ?? "—"}</b>   ·   estructuras: {loader?.LoadedModels.Count ?? 0}", small);
        GUILayout.Label($"Triángulos: {tris:N0}   ·   {fps:F0} FPS", small);
        GUILayout.Label($"OpenXR: {(XRSettings.isDeviceActive ? XRSettings.loadedDeviceName : "sin visor (vista de escritorio)")}", small);
        GUILayout.EndArea();

        GUILayout.BeginArea(new Rect(Screen.width - 470 * k, 20 * k, 450 * k, 300 * k), panel);
        GUILayout.Label("<b>Manos simuladas</b>: <color=#4099ff>●</color> izquierda  <color=#ff8c26>●</color> derecha\n" +
                        "(la esfera crece al hacer pinza)\n\n" +
                        "<b>Teclado</b>: flechas/arrastre rotar · WASD/QE mover\n" +
                        "+/- o rueda escalar · L pelar · U todo\n" +
                        "X despiece · N siguiente · R restablecer\n" +
                        (paused ? "<b>Espacio: reanudar (EN PAUSA)</b>" : "Espacio: pausar el recorrido"), small);
        GUILayout.EndArea();

        GUI.Box(new Rect(Screen.width * 0.15f, Screen.height - 110 * k, Screen.width * 0.7f, 80 * k), GUIContent.none, panel);
        GUI.Label(new Rect(Screen.width * 0.15f, Screen.height - 110 * k, Screen.width * 0.7f, 80 * k), step, caption);
    }

    private static string ArgValue(string name)
    {
        string[] args = System.Environment.GetCommandLineArgs();
        int i = System.Array.IndexOf(args, name);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
    }
}
