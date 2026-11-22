#if UNITY_EDITOR
using System.IO;
using Unity.XR.CoreUtils;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.XR;
using UnityEngine.SceneManagement;

/// <summary>
/// Construye la escena de realidad mixta: XR Origin con cámara seguida por el
/// visor, el estudio delante del usuario a la altura del pecho y los
/// controladores de carga, gestos y rendimiento.
/// </summary>
public static class NeuroHubSceneBuilder
{
    public const string ScenePath = "Assets/Scenes/NeuroHubMR.unity";
    public const string MaterialPath = "Assets/Resources/NeuroHub/NeuroHubTransparent.mat";

    [MenuItem("ATLAS/MR/Build Study Scene")]
    public static void Build()
    {
        EnsureMaterial();
        Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

        // ---------------------------------------------------------- XR Origin
        GameObject originGo = new("XR Origin");
        XROrigin origin = originGo.AddComponent<XROrigin>();
        GameObject offset = new("Camera Offset");
        offset.transform.SetParent(originGo.transform, false);
        GameObject cameraGo = new("Main Camera") { tag = "MainCamera" };
        cameraGo.transform.SetParent(offset.transform, false);
        // Pose de escritorio (sin visor); en XR la sobrescribe el seguimiento.
        cameraGo.transform.localPosition = new Vector3(0f, 1.6f, 0f);
        cameraGo.transform.localRotation = Quaternion.Euler(14f, 0f, 0f);
        Camera camera = cameraGo.AddComponent<Camera>();
        camera.clearFlags = CameraClearFlags.SolidColor;
        // Fondo negro transparente: en visores ópticos (HoloLens) el negro es
        // transparente y en passthrough (Quest) deja ver el entorno real.
        camera.backgroundColor = new Color(0f, 0f, 0f, 0f);
        camera.nearClipPlane = 0.02f;
        camera.farClipPlane = 50f;
        TrackedPoseDriver driver = cameraGo.AddComponent<TrackedPoseDriver>();
        driver.positionInput = new InputActionProperty(new InputAction(
            "Head Position", InputActionType.Value, "<XRHMD>/centerEyePosition", expectedControlType: "Vector3"));
        driver.rotationInput = new InputActionProperty(new InputAction(
            "Head Rotation", InputActionType.Value, "<XRHMD>/centerEyeRotation", expectedControlType: "Quaternion"));
        driver.ignoreTrackingState = true;
        origin.Origin = originGo;
        origin.CameraFloorOffsetObject = offset;
        origin.Camera = camera;
        origin.RequestedTrackingOriginMode = XROrigin.TrackingOriginMode.Floor;
        NeuroHubXRHandSource hands = originGo.AddComponent<NeuroHubXRHandSource>();
        hands.TrackingSpace = offset.transform;

        // ------------------------------------------------------------ Estudio
        GameObject app = new("ATLAS");
        GameObject studyRoot = new("Estudio");
        studyRoot.transform.SetParent(app.transform, false);
        // 45 cm delante del usuario, a la altura del pecho: distancia cómoda
        // para manipular con las manos sin estirar el brazo.
        studyRoot.transform.position = new Vector3(0f, 1.4f, 0.45f);
        NeuroHubStudyLoader loader = app.AddComponent<NeuroHubStudyLoader>();
        SerializedObject loaderData = new(loader);
        loaderData.FindProperty("studyRoot").objectReferenceValue = studyRoot.transform;
        loaderData.FindProperty("fallbackMaterial").objectReferenceValue =
            AssetDatabase.LoadAssetAtPath<Material>(MaterialPath);
        loaderData.ApplyModifiedPropertiesWithoutUndo();
        NeuroHubGestureController gestures = app.AddComponent<NeuroHubGestureController>();
        SerializedObject gestureData = new(gestures);
        gestureData.FindProperty("studyRoot").objectReferenceValue = studyRoot.transform;
        gestureData.FindProperty("loader").objectReferenceValue = loader;
        SerializedProperty sources = gestureData.FindProperty("handSources");
        sources.arraySize = 1;
        sources.GetArrayElementAtIndex(0).objectReferenceValue = hands;
        gestureData.ApplyModifiedPropertiesWithoutUndo();
        app.AddComponent<NeuroHubPerformanceMonitor>();

        // ----------------------------------------------------------- Lumínica
        GameObject keyGo = new("Luz_Principal");
        Light key = keyGo.AddComponent<Light>();
        key.type = LightType.Directional;
        key.intensity = 1.1f;
        key.shadows = LightShadows.None;
        keyGo.transform.rotation = Quaternion.Euler(40f, -30f, 0f);
        RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
        RenderSettings.ambientLight = new Color(0.55f, 0.57f, 0.62f);

        Directory.CreateDirectory("Assets/Scenes");
        EditorSceneManager.SaveScene(scene, ScenePath);
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
        Debug.Log($"ATLAS: escena MR creada: {ScenePath}");
    }

    public static void EnsureMaterial()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(MaterialPath));
        Material material = AssetDatabase.LoadAssetAtPath<Material>(MaterialPath);
        if (material == null)
        {
            material = new Material(Shader.Find("Universal Render Pipeline/Lit"));
            AssetDatabase.CreateAsset(material, MaterialPath);
        }
        // Plantilla transparente: garantiza que la variante del shader entra en
        // el build (el cargador clona este material por estructura).
        material.SetOverrideTag("RenderType", "Transparent");
        material.SetFloat("_Surface", 1f);
        material.SetFloat("_Blend", 0f);
        material.SetFloat("_SrcBlend", (float)UnityEngine.Rendering.BlendMode.SrcAlpha);
        material.SetFloat("_DstBlend", (float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
        material.SetFloat("_SrcBlendAlpha", (float)UnityEngine.Rendering.BlendMode.One);
        material.SetFloat("_DstBlendAlpha", (float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
        material.SetFloat("_ZWrite", 0f);
        material.SetFloat("_Smoothness", 0.45f);
        material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
        material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;
        material.SetColor("_BaseColor", new Color(0.8f, 0.8f, 0.8f, 0.5f));
        material.enableInstancing = true;
        EditorUtility.SetDirty(material);
        AssetDatabase.SaveAssets();
    }
}
#endif
