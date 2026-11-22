#if UNITY_EDITOR
using System;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

/// <summary>
/// Puntos de entrada para línea de comandos (Unity -batchmode -executeMethod):
///
///   NeuroHubBatch.Setup               importa estudios, configura OpenXR y crea la escena
///   NeuroHubBatch.PrepareSimulation   activa el Mock Runtime de OpenXR para las pruebas
///   NeuroHubBatch.FinishSimulation    vuelve a la configuración para visores reales
///   NeuroHubBatch.BuildAndroid        APK para visores autónomos OpenXR (Quest, Pico)
///   NeuroHubBatch.BuildWindows        ejecutable para PC VR / Quest Link / HoloLens remoting
/// </summary>
public static class NeuroHubBatch
{
    public static void Setup()
    {
        Run(() =>
        {
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            NeuroHubXRSetup.Configure(mockRuntime: false);
            NeuroHubSceneBuilder.Build();
            AssetDatabase.SaveAssets();
        });
    }

    public static void PrepareSimulation() => Run(() => NeuroHubXRSetup.Configure(mockRuntime: true));

    public static void FinishSimulation() => Run(() => NeuroHubXRSetup.Configure(mockRuntime: false));

    public static void BuildAndroid() => Build(BuildTarget.Android, "Builds/Android/ATLAS_MR.apk");

    public static void BuildWindows() => Build(BuildTarget.StandaloneWindows64, "Builds/Windows/ATLAS_MR.exe");

    private static void Build(BuildTarget target, string path)
    {
        Run(() =>
        {
            BuildReport report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = new[] { NeuroHubSceneBuilder.ScenePath },
                locationPathName = path,
                target = target,
                options = BuildOptions.None,
            });
            Debug.Log($"ATLAS: build {target}: {report.summary.result}, " +
                      $"{report.summary.totalSize / (1024f * 1024f):F1} MB, {report.summary.totalTime}");
            if (report.summary.result != BuildResult.Succeeded)
                throw new Exception($"Build {target} falló: {report.summary.totalErrors} errores");
        });
    }

    private static void Run(Action action)
    {
        try
        {
            action();
            if (Application.isBatchMode) EditorApplication.Exit(0);
        }
        catch (Exception error)
        {
            Debug.LogError("ATLAS: " + error);
            if (Application.isBatchMode) EditorApplication.Exit(1);
            else throw;
        }
    }
}
#endif
