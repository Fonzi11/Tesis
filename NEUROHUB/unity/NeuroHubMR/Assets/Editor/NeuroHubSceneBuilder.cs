#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class NeuroHubSceneBuilder
{
    [MenuItem("NEUROHUB/MR/Build Study Scene")]
    public static void Build()
    {
        string studies = "Assets/Resources/Studies";
        string[] manifests = Directory.Exists(studies)
            ? Directory.GetFiles(studies, "study_manifest.json", SearchOption.AllDirectories)
            : new string[0];
        if (manifests.Length == 0)
        {
            Debug.LogError("NEUROHUB: no hay study_manifest.json en Resources/Studies.");
            return;
        }

        string studyId = new DirectoryInfo(Path.GetDirectoryName(manifests[0])).Name;
        string studyRoot = Path.GetDirectoryName(manifests[0]).Replace("\\", "/");
        string brainPath = $"{studyRoot}/cerebro.fbx";
        GameObject brainPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(brainPath);
        if (brainPrefab == null)
        {
            Debug.LogError($"NEUROHUB: no se pudo importar el FBX principal: {brainPath}");
            return;
        }

        EnsureFolder("Assets/Scenes");
        EnsureFolder("Assets/Animations");
        string animationPath = "Assets/Animations/NeuroHubPresentation.anim";
        string controllerPath = "Assets/Animations/NeuroHubPresentation.controller";
        AnimationClip clip = CreatePresentationClip(animationPath);
        AnimatorController controller = CreateController(controllerPath, clip);

        Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,
            NewSceneMode.Single);
        GameObject root = new("NEUROHUB_MR_STUDY");
        NeuroHubStudyLoader loader = root.AddComponent<NeuroHubStudyLoader>();
        loader.studyId = studyId;
        loader.enabled = false;

        GameObject model = Object.Instantiate(brainPrefab);
        model.name = "Cerebro_Animable";
        model.transform.SetParent(root.transform, false);
        model.transform.localScale = Vector3.one * 0.001f;
        Animator animator = model.AddComponent<Animator>();
        animator.runtimeAnimatorController = controller;
        NeuroHubAnimationController animation = model.AddComponent<NeuroHubAnimationController>();
        animation.enabled = true;

        GameObject gestureRoot = new("Gestos_MR");
        gestureRoot.transform.SetParent(root.transform, false);
        NeuroHubGestureController gestures = gestureRoot.AddComponent<NeuroHubGestureController>();
        SerializedObject gestureData = new(gestures);
        gestureData.FindProperty("studyRoot").objectReferenceValue = model.transform;
        gestureData.ApplyModifiedPropertiesWithoutUndo();

        CreateLighting();
        CreateCamera(root.transform);
        string scenePath = "Assets/Scenes/NeuroHubMR_Presentation.unity";
        EditorSceneManager.SaveScene(scene, scenePath);
        Selection.activeGameObject = model;
        Debug.Log($"NEUROHUB: escena MR creada: {scenePath}. Modelo animable: {brainPath}");
    }

    private static void EnsureFolder(string path)
    {
        string parent = Path.GetDirectoryName(path).Replace("\\", "/");
        string name = Path.GetFileName(path);
        if (!AssetDatabase.IsValidFolder(path))
            AssetDatabase.CreateFolder(parent, name);
    }

    private static AnimationClip CreatePresentationClip(string path)
    {
        AnimationClip clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
        if (clip == null)
        {
            clip = new AnimationClip { name = "NeuroHubPresentation" };
            AssetDatabase.CreateAsset(clip, path);
        }
        clip.frameRate = 60f;
        clip.wrapMode = WrapMode.Loop;
        AnimationCurve curve = AnimationCurve.EaseInOut(0f, 0f, 12f, 360f);
        clip.SetCurve("", typeof(Transform), "localEulerAngles.y", curve);
        EditorUtility.SetDirty(clip);
        AssetDatabase.SaveAssets();
        return clip;
    }

    private static AnimatorController CreateController(string path, AnimationClip clip)
    {
        AnimatorController controller =
            AssetDatabase.LoadAssetAtPath<AnimatorController>(path);
        if (controller == null)
            controller = AnimatorController.CreateAnimatorControllerAtPath(path);
        AnimatorStateMachine machine = controller.layers[0].stateMachine;
        foreach (ChildAnimatorState child in machine.states)
            machine.RemoveState(child.state);
        AnimatorState state = machine.AddState("NeuroHubPresentation");
        state.motion = clip;
        machine.defaultState = state;
        EditorUtility.SetDirty(controller);
        AssetDatabase.SaveAssets();
        return controller;
    }

    private static void CreateLighting()
    {
        GameObject keyObject = new("Luz_Principal");
        Light key = keyObject.AddComponent<Light>();
        key.type = LightType.Directional;
        key.intensity = 1.5f;
        key.color = new Color(0.78f, 0.88f, 1f);
        keyObject.transform.rotation = Quaternion.Euler(35f, -35f, 0f);

        GameObject rimObject = new("Luz_Rim");
        Light rim = rimObject.AddComponent<Light>();
        rim.type = LightType.Point;
        rim.intensity = 650f;
        rim.range = 8f;
        rim.color = new Color(0.25f, 0.55f, 1f);
        rimObject.transform.position = new Vector3(-2f, 1.5f, -2f);
    }

    private static void CreateCamera(Transform target)
    {
        GameObject cameraObject = new("Main Camera");
        Camera camera = cameraObject.AddComponent<Camera>();
        camera.tag = "MainCamera";
        camera.fieldOfView = 42f;
        cameraObject.transform.position = new Vector3(0f, 0.2f, -3.2f);
        cameraObject.transform.LookAt(target.position + Vector3.up * 0.15f);
    }
}
#endif
