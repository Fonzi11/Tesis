#if UNITY_EDITOR
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.XR.Management;
using UnityEngine.XR.OpenXR;
using UnityEngine.XR.OpenXR.Features;

/// <summary>
/// Configura OpenXR de forma reproducible (sin pasos manuales en el Editor):
/// loader OpenXR en Windows (PC VR / Quest Link / HoloLens remoting) y en
/// Android (Quest, Pico y otros visores autónomos), seguimiento de manos por la
/// extensión estándar XR_EXT_hand_tracking y perfiles de interacción de varios
/// fabricantes. Es la base de la portabilidad entre visores (RD5).
/// </summary>
public static class NeuroHubXRSetup
{
    private const string Loader = "UnityEngine.XR.OpenXR.OpenXRLoader";
    private const string SettingsPath = "Assets/XR/XRGeneralSettingsPerBuildTarget.asset";

    // Características comunes (nombres de tipo de las features de OpenXR/XR Hands).
    private static readonly string[] Common =
    {
        "HandTracking",                 // XR_EXT_hand_tracking (XR Hands)
        "MetaHandTrackingAim",          // XR_FB_hand_tracking_aim (pinza del sistema en Meta)
        "HandInteractionProfile",       // XR_EXT_hand_interaction (estándar Khronos)
        "HandCommonPosesInteraction",
        "PalmPoseInteraction",
        "MicrosoftHandInteraction",     // HoloLens 2 / WMR
        "KHRSimpleControllerProfile",
        "OculusTouchControllerProfile",
        "MetaQuestTouchProControllerProfile",
    };
    private static readonly string[] AndroidOnly = { "MetaQuestFeature" };
    private static readonly string[] Disabled =
    {
        "MockRuntime", "ConformanceAutomationFeature", "RuntimeDebuggerOpenXRFeature",
        "OculusQuestFeature", "EyeGazeInteraction",
    };

    [MenuItem("ATLAS/MR/Configurar OpenXR")]
    public static void Configure() => Configure(mockRuntime: false);

    public static void Configure(bool mockRuntime)
    {
        XRGeneralSettingsPerBuildTarget perTarget = GetOrCreatePerTarget();
        foreach (BuildTargetGroup group in new[] { BuildTargetGroup.Standalone, BuildTargetGroup.Android })
        {
            if (!perTarget.HasSettingsForBuildTarget(group))
                perTarget.CreateDefaultSettingsForBuildTarget(group);
            if (!perTarget.HasManagerSettingsForBuildTarget(group))
                perTarget.CreateDefaultManagerSettingsForBuildTarget(group);
            XRGeneralSettings general = perTarget.SettingsForBuildTarget(group);
            // En la simulación el loader se inicializa desde la prueba.
            general.InitManagerOnStart = !mockRuntime;
            if (!general.Manager.activeLoaders.Any(l => l != null && l.GetType().FullName == Loader))
                XRPackageMetadataStore.AssignLoader(general.Manager, Loader, group);
            EditorUtility.SetDirty(general);
            EditorUtility.SetDirty(general.Manager);

            OpenXRSettings openxr = OpenXRSettings.GetSettingsForBuildTargetGroup(group);
            if (openxr == null)
            {
                Debug.LogError($"ATLAS: no hay OpenXRSettings para {group}.");
                continue;
            }
            HashSet<string> enable = new(Common);
            if (group == BuildTargetGroup.Android) enable.UnionWith(AndroidOnly);
            if (mockRuntime && group == BuildTargetGroup.Standalone) enable.Add("MockRuntime");
            foreach (OpenXRFeature feature in openxr.GetFeatures())
            {
                string type = feature.GetType().Name;
                if (enable.Contains(type)) feature.enabled = true;
                else if (Disabled.Contains(type)) feature.enabled = false;
                EditorUtility.SetDirty(feature);
            }
            openxr.renderMode = OpenXRSettings.RenderMode.SinglePassInstanced;
            EditorUtility.SetDirty(openxr);
            Debug.Log($"ATLAS: OpenXR {group}: " + string.Join(", ",
                openxr.GetFeatures().Where(f => f.enabled).Select(f => f.GetType().Name)));
        }

        ConfigurePlayer();
        NeuroHubRenderSetup.Ensure();
        EditorUtility.SetDirty(perTarget);
        AssetDatabase.SaveAssets();
    }

    private static XRGeneralSettingsPerBuildTarget GetOrCreatePerTarget()
    {
        if (EditorBuildSettings.TryGetConfigObject(XRGeneralSettings.k_SettingsKey,
                out XRGeneralSettingsPerBuildTarget existing) && existing != null)
            return existing;
        XRGeneralSettingsPerBuildTarget created =
            AssetDatabase.LoadAssetAtPath<XRGeneralSettingsPerBuildTarget>(SettingsPath);
        if (created == null)
        {
            created = ScriptableObject.CreateInstance<XRGeneralSettingsPerBuildTarget>();
            AssetDatabase.CreateAsset(created, SettingsPath);
        }
        EditorBuildSettings.AddConfigObject(XRGeneralSettings.k_SettingsKey, created, true);
        return created;
    }

    private static void ConfigurePlayer()
    {
        PlayerSettings.companyName = "ATLAS";
        PlayerSettings.productName = "ATLAS MR";
        PlayerSettings.colorSpace = ColorSpace.Linear;
        PlayerSettings.SetApplicationIdentifier(BuildTargetGroup.Android, "com.atlas.mr");
        PlayerSettings.SetScriptingBackend(BuildTargetGroup.Android, ScriptingImplementation.IL2CPP);
        PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
        PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel29;
        PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
        PlayerSettings.SetGraphicsAPIs(BuildTarget.Android,
            new[] { GraphicsDeviceType.Vulkan, GraphicsDeviceType.OpenGLES3 });
    }
}
#endif
