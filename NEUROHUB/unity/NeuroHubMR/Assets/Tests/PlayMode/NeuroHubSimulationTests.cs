using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.TestTools;
using UnityEngine.XR;
using UnityEngine.XR.Hands;
using UnityEngine.XR.Management;
using Debug = UnityEngine.Debug;

/// <summary>
/// Simulaciones del prototipo ATLAS MR (ejecutables sin visor):
///  1. Carga de cada estudio: todas las estructuras, lesión presente, escala real.
///  2. Gestos con manos simuladas: traslación, rotación, escalado, límites,
///     pelado de capas, despiece y restablecer (RD5).
///  3. Rendimiento: render estéreo a la resolución por ojo de Meta Quest 3 (RD4).
///  4. OpenXR con el Mock Runtime oficial: inicialización del loader, sesión y
///     subsistemas de pantalla/entrada/manos.
/// Los resultados se guardan en SimulationResults/simulacion_resultados.json.
/// </summary>
public sealed class NeuroHubSimulationTests
{
    private const int EyeWidth = 2064, EyeHeight = 2208; // Meta Quest 3, por ojo
    private const int PerfFrames = 120;

    private static readonly Dictionary<string, object> Results = new();

    public static IEnumerable<string> AllStudies()
    {
        TextAsset idx = Resources.Load<TextAsset>("Studies/studies_index");
        if (idx == null) return new[] { "sin_indice" };
        NeuroHubStudyIndex index = JsonUtility.FromJson<NeuroHubStudyIndex>(idx.text);
        return index.studies.Concat(index.lightStudies ?? new string[0]);
    }

    public static IEnumerable<string> FullStudies()
    {
        TextAsset idx = Resources.Load<TextAsset>("Studies/studies_index");
        return idx == null ? new[] { "sin_indice" }
            : JsonUtility.FromJson<NeuroHubStudyIndex>(idx.text).studies;
    }

    private GameObject app;
    private NeuroHubStudyLoader loader;
    private Transform root;

    [UnitySetUp]
    public IEnumerator SetUp()
    {
        app = new GameObject("ATLAS_test");
        root = new GameObject("Estudio").transform;
        root.SetParent(app.transform, false);
        root.position = new Vector3(0f, 1.4f, 0.45f);
        app.SetActive(false);
        loader = app.AddComponent<NeuroHubStudyLoader>();
        SetPrivate(loader, "studyRoot", root);
        SetPrivate(loader, "loadOnStart", false);
        app.SetActive(true);
        yield return null;
    }

    [UnityTearDown]
    public IEnumerator TearDown()
    {
        Object.Destroy(app);
        yield return null;
        Resources.UnloadUnusedAssets();
    }

    [OneTimeTearDown]
    public void Save()
    {
        string dir = Path.Combine(Application.dataPath, "..", "SimulationResults");
        Directory.CreateDirectory(dir);
        string path = Path.Combine(dir, "simulacion_resultados.json");
        File.WriteAllText(path, MiniJson(Results));
        Debug.Log("ATLAS: resultados de simulación en " + Path.GetFullPath(path));
    }

    // ------------------------------------------------------------ 1. carga
    [UnityTest]
    public IEnumerator Estudio_CargaCompletaConLesionYEscalaReal(
        [ValueSource(nameof(AllStudies))] string studyId)
    {
        Stopwatch sw = Stopwatch.StartNew();
        yield return loader.LoadStudy(studyId);
        sw.Stop();

        NeuroHubStudyManifest m = loader.Manifest;
        Assert.IsNotNull(m, $"Sin manifiesto para {studyId}");
        Assert.AreEqual(m.models.Length, loader.LoadedModels.Count,
            "No se cargaron todas las estructuras del manifiesto");

        string[] lesion = m.models.Where(x => x.group == "lesion").Select(x => x.id).ToArray();
        Assert.IsNotEmpty(lesion, "El estudio no tiene lesión (tumor o aneurisma)");
        foreach (string id in lesion)
            Assert.IsTrue(loader.LoadedModels[id].activeInHierarchy, $"Lesión {id} oculta");

        Bounds brain = WorldBounds(m, x => x.group == "corteza");
        Bounds lesionBounds = WorldBounds(m, x => x.group == "lesion");
        Vector3 size = brain.size;
        // Cerebro adulto: ~13-18 cm de largo. Verifica que la escala es real (1:1).
        Assert.That(size.z, Is.InRange(0.12f, 0.21f), $"Longitud A-P {size.z:F3} m fuera de rango");
        Assert.That(size.x, Is.InRange(0.10f, 0.19f), $"Anchura {size.x:F3} m fuera de rango");
        Bounds inner = brain;
        inner.Expand(0.01f);
        Assert.IsTrue(inner.Contains(lesionBounds.center), "La lesión no está dentro del cerebro");

        int tris = 0;
        int transparent = 0;
        foreach (GameObject go in loader.LoadedModels.Values)
        {
            foreach (MeshFilter mf in go.GetComponentsInChildren<MeshFilter>())
                for (int sm = 0; sm < mf.sharedMesh.subMeshCount; sm++)
                    tris += (int)mf.sharedMesh.GetIndexCount(sm) / 3;
            foreach (Renderer r in go.GetComponentsInChildren<Renderer>())
                if (r.sharedMaterial.renderQueue >= (int)RenderQueue.Transparent) transparent++;
        }
        Assert.Greater(transparent, 0, "Ningún material transparente");

        Results[$"carga/{studyId}"] = new Dictionary<string, object>
        {
            ["estructuras"] = loader.LoadedModels.Count,
            ["lesion"] = m.lesionType,
            ["capas_lesion"] = string.Join(",", lesion),
            ["triangulos"] = tris,
            ["materiales_transparentes"] = transparent,
            ["tiempo_carga_s"] = sw.Elapsed.TotalSeconds,
            ["cerebro_tamano_m"] = new[] { size.x, size.y, size.z },
            ["lesion_tamano_m"] = new[] { lesionBounds.size.x, lesionBounds.size.y, lesionBounds.size.z },
        };
    }

    // ------------------------------------------------------------ 2. gestos
    [UnityTest]
    public IEnumerator Gestos_ManosSimuladas([ValueSource(nameof(FullStudies))] string studyId)
    {
        yield return loader.LoadStudy(studyId);
        NeuroHubSimulatedHandSource hands = app.AddComponent<NeuroHubSimulatedHandSource>();
        NeuroHubGestureController ctl = app.AddComponent<NeuroHubGestureController>();
        ctl.Configure(root, loader, hands);
        ctl.enabled = false; // los pasos los da la simulación, con tiempo controlado
        float t = 0f;
        var checks = new Dictionary<string, object>();

        void Frame(NeuroHubHandState l, NeuroHubHandState r)
        {
            hands.left = l;
            hands.right = r;
            t += 1f / 72f; // 72 Hz, tasa típica de Quest
            ctl.Step(t);
        }

        NeuroHubHandState none = default;

        // a) Traslación: pinza derecha y desplazamiento de 10 cm.
        Vector3 p0 = root.position + new Vector3(0.1f, 0f, -0.05f);
        Vector3 start = root.position;
        for (int i = 0; i <= 30; i++)
            Frame(none, NeuroHubSimulatedHandSource.Hand(p0 + Vector3.right * (0.1f * i / 30f), true));
        Frame(none, none);
        float moved = Vector3.Distance(root.position, start + Vector3.right * 0.1f);
        Assert.Less(moved, 0.001f, $"Traslación con error {moved * 1000f:F2} mm");
        checks["traslacion_error_mm"] = moved * 1000f;

        // b) Rotación: girar la muñeca 30° alrededor del eje vertical.
        Quaternion r0 = root.rotation;
        for (int i = 0; i <= 30; i++)
            Frame(none, NeuroHubSimulatedHandSource.Hand(p0, true, Quaternion.Euler(0f, 30f * i / 30f, 0f)));
        Frame(none, none);
        float angle = Quaternion.Angle(r0, root.rotation);
        Assert.That(angle, Is.EqualTo(30f).Within(0.5f), "Rotación incorrecta");
        checks["rotacion_grados"] = angle;

        // c) Escalado con dos manos: separar de 20 cm a 30 cm => x1.5.
        float s0 = root.localScale.x;
        Vector3 c = root.position;
        for (int i = 0; i <= 30; i++)
        {
            float half = Mathf.Lerp(0.10f, 0.15f, i / 30f);
            Frame(NeuroHubSimulatedHandSource.Hand(c - Vector3.right * half, true),
                  NeuroHubSimulatedHandSource.Hand(c + Vector3.right * half, true));
        }
        Frame(none, none);
        float ratio = root.localScale.x / s0;
        Assert.That(ratio, Is.EqualTo(1.5f).Within(0.01f), "Escalado incorrecto");
        checks["escala_factor"] = ratio;

        // d) Límite de escala: separar hasta 2 m no supera maxScale.
        for (int i = 0; i <= 10; i++)
        {
            float half = Mathf.Lerp(0.10f, 1.0f, i / 10f);
            Frame(NeuroHubSimulatedHandSource.Hand(c - Vector3.right * half, true),
                  NeuroHubSimulatedHandSource.Hand(c + Vector3.right * half, true));
        }
        Frame(none, none);
        Assert.LessOrEqual(root.localScale.x, ctl.Solver.maxScale + 1e-4f, "No se respetó la escala máxima");
        checks["escala_maxima_respetada"] = true;

        // e) Toque izquierdo: pelar la capa más externa.
        string firstGroup = NeuroHubStudyLoader.PeelOrder.First(g => loader.GroupsPresent().Contains(g));
        Frame(NeuroHubSimulatedHandSource.Hand(c, true), none);
        Frame(NeuroHubSimulatedHandSource.Hand(c, true), none);
        Frame(none, none);
        Assert.IsFalse(loader.IsGroupVisible(firstGroup), $"El toque no ocultó {firstGroup}");
        Assert.IsTrue(loader.IsGroupVisible("lesion"), "La lesión se ocultó");
        checks["toque_izquierdo_oculta"] = firstGroup;

        // f) Toque derecho: despiece animado.
        string probe = loader.Manifest.models.First(x => x.group != "lesion" && x.group != "vasos").id;
        Vector3 before = loader.LoadedModels[probe].transform.localPosition;
        Frame(none, NeuroHubSimulatedHandSource.Hand(c, true));
        Frame(none, NeuroHubSimulatedHandSource.Hand(c, true));
        Frame(none, none);
        // La animación avanza en tiempo real: se espera hasta 2 s reales.
        float until = Time.realtimeSinceStartup + 2f;
        while (loader.Explode < 0.999f && Time.realtimeSinceStartup < until) yield return null;
        float sep = Vector3.Distance(before, loader.LoadedModels[probe].transform.localPosition);
        Assert.Greater(sep, 0.02f, "El despiece no separó las capas");
        checks["despiece_separacion_m"] = sep;

        // g) Pinza breve con ambas manos, sin moverlas: restablecer.
        Frame(NeuroHubSimulatedHandSource.Hand(c - Vector3.right * 0.2f, true),
              NeuroHubSimulatedHandSource.Hand(c + Vector3.right * 0.2f, true));
        Frame(NeuroHubSimulatedHandSource.Hand(c - Vector3.right * 0.2f, true),
              NeuroHubSimulatedHandSource.Hand(c + Vector3.right * 0.2f, true));
        Frame(none, none);
        Assert.That(root.localScale.x, Is.EqualTo(s0).Within(1e-4f));
        Assert.IsTrue(loader.IsGroupVisible(firstGroup), "Restablecer no mostró las capas");
        checks["restablecer"] = true;

        Results[$"gestos/{studyId}"] = checks;
    }

    // ------------------------------------------------ 3a. render correcto (URP)
    /// <summary>
    /// Sin un pipeline URP asignado los materiales de los modelos se dibujan en
    /// magenta de error y las cifras de rendimiento no significan nada. Esta
    /// prueba renderiza cada estudio y exige URP activo, modelo visible y
    /// ningún píxel magenta.
    /// </summary>
    [UnityTest]
    public IEnumerator Render_URPActivoSinShadersDeError([ValueSource(nameof(FullStudies))] string studyId)
    {
        RenderPipelineAsset pipeline = GraphicsSettings.currentRenderPipeline;
        Assert.IsNotNull(pipeline, "No hay pipeline asignado: los materiales URP salen en magenta");
        StringAssert.Contains("Universal", pipeline.GetType().Name);

        yield return loader.LoadStudy(studyId);
        GameObject camGo = new("Camara_Verificacion");
        Camera cam = camGo.AddComponent<Camera>();
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = Color.black;
        cam.nearClipPlane = 0.02f;
        cam.fieldOfView = 40f;
        GameObject lightGo = new("Luz_Verificacion");
        lightGo.AddComponent<Light>().type = LightType.Directional;
        lightGo.transform.rotation = Quaternion.Euler(40f, -30f, 0f);
        camGo.transform.position = root.position + new Vector3(0f, 0.1f, -0.5f);
        camGo.transform.LookAt(root.position);
        const int size = 256;
        RenderTexture rt = new(size, size, 24, RenderTextureFormat.ARGB32);
        cam.targetTexture = rt;
        cam.Render();
        RenderTexture.active = rt;
        Texture2D tex = new(size, size, TextureFormat.RGBA32, false);
        tex.ReadPixels(new Rect(0, 0, size, size), 0, 0);
        tex.Apply();
        RenderTexture.active = null;
        cam.targetTexture = null;
        rt.Release();
        Object.Destroy(camGo);
        Object.Destroy(lightGo);

        int lit = 0, magenta = 0;
        foreach (Color32 c in tex.GetPixels32())
        {
            if (c.r + c.g + c.b > 30) lit++;
            if (c.r > 200 && c.b > 200 && c.g < 60) magenta++;
        }
        Object.Destroy(tex);
        int bad = 0;
        foreach (GameObject go in loader.LoadedModels.Values)
        foreach (Renderer r in go.GetComponentsInChildren<Renderer>())
            if (r.sharedMaterial == null || !r.sharedMaterial.shader.isSupported ||
                !r.sharedMaterial.shader.name.StartsWith("Universal Render Pipeline")) bad++;

        Results[$"render/{studyId}"] = new Dictionary<string, object>
        {
            ["pipeline"] = pipeline.name,
            ["pixeles_modelo"] = lit,
            ["pixeles_magenta"] = magenta,
            ["materiales_no_urp"] = bad,
        };
        Assert.AreEqual(0, bad, "Materiales sin shader URP soportado");
        Assert.Greater(lit, size * size / 50, "El modelo no aparece en la imagen");
        Assert.Less(magenta, size * size / 1000, "Píxeles magenta: shader de error");
    }

    // ------------------------------------------------------- 3. rendimiento
    [UnityTest]
    public IEnumerator Rendimiento_RenderEstereoQuest3([ValueSource(nameof(AllStudies))] string studyId)
    {
        yield return loader.LoadStudy(studyId);
        GameObject camGo = new("Camara_Ojo");
        Camera cam = camGo.AddComponent<Camera>();
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0, 0, 0, 0);
        cam.nearClipPlane = 0.02f;
        cam.fieldOfView = 96f; // FOV vertical aproximado de Quest 3
        cam.aspect = EyeWidth / (float)EyeHeight;
        var desc = new RenderTextureDescriptor(EyeWidth, EyeHeight, RenderTextureFormat.ARGB32, 24)
            { msaaSamples = 4 };
        RenderTexture left = new(desc), right = new(desc);
        left.Create();
        right.Create();
        Vector3 head = root.position + new Vector3(0f, 0.2f, -0.45f);
        const float ipd = 0.064f;

        var ms = new List<double>();
        for (int f = 0; f < PerfFrames + 10; f++)
        {
            root.Rotate(Vector3.up, 3f, Space.World);
            Stopwatch sw = Stopwatch.StartNew();
            foreach ((RenderTexture rt, float side) in new[] { (left, -1f), (right, 1f) })
            {
                camGo.transform.position = head + Vector3.right * (side * ipd * 0.5f);
                camGo.transform.LookAt(root.position);
                cam.targetTexture = rt;
                cam.Render();
            }
            // Espera a que la GPU termine: tiempo real CPU+GPU del cuadro.
            AsyncGPUReadback.Request(right, 0, 0, 1, 0, 1, 0, 1).WaitForCompletion();
            sw.Stop();
            if (f >= 10) ms.Add(sw.Elapsed.TotalMilliseconds); // descarta calentamiento
            yield return null;
        }
        cam.targetTexture = null;
        left.Release();
        right.Release();
        Object.Destroy(camGo);

        ms.Sort();
        double mean = ms.Average();
        double p95 = ms[(int)(ms.Count * 0.95) - 1];
        Results[$"rendimiento/{studyId}"] = new Dictionary<string, object>
        {
            ["resolucion_por_ojo"] = $"{EyeWidth}x{EyeHeight} MSAA4",
            ["cuadros"] = ms.Count,
            ["ms_medio"] = mean,
            ["ms_p95"] = p95,
            ["fps_medio"] = 1000.0 / mean,
            ["fps_p95"] = 1000.0 / p95,
            ["gpu"] = SystemInfo.graphicsDeviceName,
        };
        Assert.Greater(1000.0 / p95, 30.0, "Por debajo de 30 FPS (RD4) en el percentil 95");
    }

    // ----------------------------------------------------- 4. OpenXR (mock)
    [UnityTest]
    public IEnumerator OpenXR_MockRuntime_SesionYSubsistemas()
    {
        XRGeneralSettings general = XRGeneralSettings.Instance;
        Assert.IsNotNull(general, "No hay XRGeneralSettings (OpenXR sin configurar)");
        XRManagerSettings manager = general.Manager;
        Assert.IsNotNull(manager, "No hay XRManagerSettings");
        Assert.IsTrue(manager.activeLoaders.Any(l => l != null && l.GetType().Name == "OpenXRLoader"),
            "El loader OpenXR no está asignado");

        if (manager.activeLoader == null)
            yield return manager.InitializeLoader();
        Assert.IsNotNull(manager.activeLoader, "OpenXR no pudo inicializarse (¿Mock Runtime activo?)");
        manager.StartSubsystems();
        // La sesión pasa por IDLE -> READY -> SYNCHRONIZED -> VISIBLE -> FOCUSED
        // en los primeros cuadros; se espera hasta 5 s reales a que la pantalla
        // XR esté activa.
        var displays = new List<XRDisplaySubsystem>();
        float t0 = Time.realtimeSinceStartup;
        do
        {
            yield return null;
            displays.Clear();
            SubsystemManager.GetSubsystems(displays);
        } while (!displays.Any(d => d.running) && Time.realtimeSinceStartup - t0 < 5f);
        float secondsToDisplay = Time.realtimeSinceStartup - t0;
        var inputs = new List<XRInputSubsystem>();
        SubsystemManager.GetSubsystems(inputs);
        var handSubs = new List<XRHandSubsystem>();
        SubsystemManager.GetSubsystems(handSubs);
        bool displayRunning = displays.Any(d => d.running);

        // Carga de un estudio con el visor (simulado) activo y 2 s de render XR.
        string first = FullStudies().First();
        yield return loader.LoadStudy(first);
        int xrFrames = 0;
        float t1 = Time.realtimeSinceStartup;
        while (Time.realtimeSinceStartup - t1 < 2f) { xrFrames++; yield return null; }
        float xrFps = xrFrames / (Time.realtimeSinceStartup - t1);

        Results["openxr/mock_runtime"] = new Dictionary<string, object>
        {
            ["loader"] = manager.activeLoader.GetType().Name,
            ["runtime"] = UnityEngine.XR.OpenXR.OpenXRRuntime.name,
            ["runtime_version"] = UnityEngine.XR.OpenXR.OpenXRRuntime.version,
            ["display_activo"] = displayRunning,
            ["segundos_hasta_display"] = secondsToDisplay,
            ["cuadros_xr_en_2s"] = xrFrames,
            ["fps_bucle_xr"] = xrFps,
            ["nota_manos"] = "El Mock Runtime no implementa XR_EXT_hand_tracking; los gestos se validan con manos simuladas.",
            ["subsistemas_entrada"] = inputs.Count(s => s.running),
            ["subsistema_manos_registrado"] = handSubs.Count > 0,
            ["subsistema_manos_activo"] = handSubs.Any(h => h.running),
            ["extension_hand_tracking"] = UnityEngine.XR.OpenXR.OpenXRRuntime.IsExtensionEnabled("XR_EXT_hand_tracking"),
            ["estudio_cargado_con_xr"] = first,
        };

        string runtimeName = UnityEngine.XR.OpenXR.OpenXRRuntime.name;
        manager.StopSubsystems();
        manager.DeinitializeLoader();
        Assert.AreEqual("Unity Mock Runtime", runtimeName,
            "OpenXR no se conectó al runtime de simulación");
        // En -batchmode el Editor no dibuja la vista de juego y la sesión no
        // pasa de READY; la pantalla XR se valida ejecutando el reproductor
        // real (ATLAS_MR.exe -atlas-simulacion).
        if (!Application.isBatchMode)
            Assert.IsTrue(displayRunning, "El subsistema de pantalla XR no arrancó");
    }

    // ------------------------------------------------------------- utilidades
    private Bounds WorldBounds(NeuroHubStudyManifest m, System.Func<NeuroHubModel, bool> pick)
    {
        bool any = false;
        Bounds b = default;
        foreach (NeuroHubModel model in m.models.Where(pick))
        foreach (Renderer r in loader.LoadedModels[model.id].GetComponentsInChildren<Renderer>())
        {
            if (!any) { b = r.bounds; any = true; }
            else b.Encapsulate(r.bounds);
        }
        Assert.IsTrue(any, "Grupo sin geometría");
        return b;
    }

    private static void SetPrivate(object target, string field, object value)
    {
        target.GetType().GetField(field, System.Reflection.BindingFlags.Instance |
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Public)!
            .SetValue(target, value);
    }

    private static string MiniJson(object o)
    {
        switch (o)
        {
            case null: return "null";
            case string s: return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
            case bool b: return b ? "true" : "false";
            case float f: return f.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
            case double d: return d.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
            case int i: return i.ToString(System.Globalization.CultureInfo.InvariantCulture);
            case IDictionary<string, object> dict:
                return "{" + string.Join(",", dict.OrderBy(k => k.Key)
                    .Select(kv => MiniJson(kv.Key) + ":" + MiniJson(kv.Value))) + "}";
            case IEnumerable e:
                return "[" + string.Join(",", e.Cast<object>().Select(MiniJson)) + "]";
            default: return MiniJson(o.ToString());
        }
    }
}
