using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;
using UnityEngine.XR;
using UnityEngine.XR.Management;

/// <summary>
/// Simulación automática del reproductor real. Se activa solo con el argumento
/// de línea de comandos <c>-atlas-simulacion</c>:
///
///   ATLAS_MR.exe -atlas-simulacion [-salida ruta.json]
///
/// Arranca OpenXR (en simulación, con el Mock Runtime oficial), recorre los
/// estudios del índice y en cada uno mide el ritmo de cuadros XR, aplica una
/// secuencia de gestos con manos simuladas (traslación, rotación, escala,
/// pelado de capas, despiece y restablecer) y guarda un informe JSON. Después
/// cierra la aplicación. Sin el argumento no hace nada.
/// </summary>
public sealed class NeuroHubAutoSimulation : MonoBehaviour
{
    private const string Flag = "-atlas-simulacion";
    private readonly StringBuilder json = new();

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Boot()
    {
        if (!System.Environment.GetCommandLineArgs().Contains(Flag)) return;
        new GameObject("ATLAS_Simulacion").AddComponent<NeuroHubAutoSimulation>();
    }

    private IEnumerator Start()
    {
        QualitySettings.vSyncCount = 0;
        Application.targetFrameRate = -1;
        string output = ArgValue("-salida") ??
                        Path.Combine(Path.GetDirectoryName(Application.dataPath) ?? ".", "simulacion_player.json");
        NeuroHubStudyLoader loader = FindObjectOfType<NeuroHubStudyLoader>();
        NeuroHubGestureController gestures = FindObjectOfType<NeuroHubGestureController>();
        if (loader == null || gestures == null)
        {
            Write(output, "{\"error\":\"La escena no contiene el cargador o el controlador de gestos\"}");
            Application.Quit(2);
            yield break;
        }

        // ---------------------------------------------------------- OpenXR
        XRManagerSettings manager = XRGeneralSettings.Instance != null ? XRGeneralSettings.Instance.Manager : null;
        if (manager != null && manager.activeLoader == null)
        {
            yield return manager.InitializeLoader();
            if (manager.activeLoader != null) manager.StartSubsystems();
        }
        var displays = new List<XRDisplaySubsystem>();
        float t0 = Time.realtimeSinceStartup;
        do
        {
            yield return null;
            displays.Clear();
            SubsystemManager.GetSubsystems(displays);
        } while (!displays.Any(d => d.running) && Time.realtimeSinceStartup - t0 < 10f);
        bool displayRunning = displays.Any(d => d.running);

        json.Append("{");
        Field("openxr_loader", manager?.activeLoader != null ? manager.activeLoader.GetType().Name : "ninguno");
        Field("openxr_runtime", UnityEngine.XR.OpenXR.OpenXRRuntime.name);
        Field("display_activo", displayRunning);
        Field("segundos_hasta_display", Time.realtimeSinceStartup - t0);
        Field("xr_dispositivo", XRSettings.loadedDeviceName);
        Field("ojo_ancho", XRSettings.eyeTextureWidth);
        Field("ojo_alto", XRSettings.eyeTextureHeight);
        Field("modo_render", XRSettings.stereoRenderingMode.ToString());
        Field("gpu", SystemInfo.graphicsDeviceName);
        json.Append("\"estudios\":[");

        // ---------------------------------------------------- por estudio
        NeuroHubSimulatedHandSource hands = gestures.gameObject.AddComponent<NeuroHubSimulatedHandSource>();
        // Las manos reales (si el runtime las ofrece) conservan prioridad; las
        // simuladas se añaden como segunda fuente.
        NeuroHubHandSource[] sources = FindObjectsOfType<NeuroHubHandSource>()
            .Where(s => s != hands).Append(hands).ToArray();
        gestures.Configure(loader.StudyRoot, loader, sources);
        string[] studies = loader.StudyIndex.Length > 0 ? loader.StudyIndex : new[] { loader.studyId };
        for (int i = 0; i < studies.Length; i++)
        {
            yield return loader.LoadStudy(studies[i]);
            NeuroHubStudyManifest m = loader.Manifest;
            int tris = 0;
            foreach (GameObject go in loader.LoadedModels.Values)
            foreach (MeshFilter mf in go.GetComponentsInChildren<MeshFilter>())
                for (int s = 0; s < mf.sharedMesh.subMeshCount; s++)
                    tris += (int)mf.sharedMesh.GetIndexCount(s) / 3;

            var frames = new List<float>();
            float tStart = Time.realtimeSinceStartup;
            while (Time.realtimeSinceStartup - tStart < 3f)
            {
                loader.StudyRoot.Rotate(Vector3.up, 60f * Time.unscaledDeltaTime, Space.World);
                yield return null;
                frames.Add(Time.unscaledDeltaTime);
            }
            frames.Sort();
            float mean = frames.Average();
            float p95 = frames[Mathf.Clamp((int)(frames.Count * 0.95f), 0, frames.Count - 1)];

            // Gestos con manos simuladas sobre la app real.
            Vector3 c = loader.StudyRoot.position;
            yield return Pinch(hands, false, c + Vector3.right * 0.1f, Vector3.right * 0.1f, 30);  // trasladar
            yield return Pinch(hands, true, c, Vector3.zero, 2);                                     // toque izq.
            bool peeled = loader.GroupsPresent().Any(g => !loader.IsGroupVisible(g));
            yield return Pinch(hands, false, c, Vector3.zero, 2);                                    // toque der.
            float until = Time.realtimeSinceStartup + 2f;
            while (loader.Explode < 0.999f && Time.realtimeSinceStartup < until) yield return null;
            float explode = loader.Explode;
            gestures.ResetTransform();

            if (i > 0) json.Append(",");
            json.Append("{");
            Field("estudio", studies[i]);
            Field("lesion", m != null ? m.lesionType : "?");
            Field("estructuras", loader.LoadedModels.Count);
            Field("triangulos", tris);
            Field("cuadros", frames.Count);
            Field("fps_medio", 1f / mean);
            Field("fps_p95", 1f / p95);
            Field("gesto_pelar_ok", peeled);
            Field("gesto_despiece", explode, last: true);
            json.Append("}");
        }
        json.Append("]}");
        Write(output, json.ToString());

        if (manager != null && manager.activeLoader != null)
        {
            manager.StopSubsystems();
            manager.DeinitializeLoader();
        }
        Application.Quit(displayRunning ? 0 : 3);
    }

    private static IEnumerator Pinch(NeuroHubSimulatedHandSource hands, bool left, Vector3 at, Vector3 move, int frames)
    {
        for (int f = 0; f <= frames; f++)
        {
            NeuroHubHandState h = NeuroHubSimulatedHandSource.Hand(at + move * (f / (float)Mathf.Max(1, frames)), true);
            if (left) { hands.left = h; hands.right = default; }
            else { hands.right = h; hands.left = default; }
            yield return null;
        }
        hands.left = hands.right = default;
        yield return null;
    }

    private void Field(string key, object value, bool last = false)
    {
        string v = value switch
        {
            string s => "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"",
            bool b => b ? "true" : "false",
            float f => f.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
            _ => System.Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture),
        };
        json.Append('"').Append(key).Append("\":").Append(v);
        if (!last) json.Append(',');
    }

    private static string ArgValue(string name)
    {
        string[] args = System.Environment.GetCommandLineArgs();
        int i = System.Array.IndexOf(args, name);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
    }

    private static void Write(string path, string content)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)) ?? ".");
        File.WriteAllText(path, content);
        Debug.Log("ATLAS: simulación guardada en " + path);
    }
}
