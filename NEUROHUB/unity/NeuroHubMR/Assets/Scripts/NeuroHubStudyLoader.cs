using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

[Serializable]
public class NeuroHubModel
{
    public string id;
    public string file;
    public float[] color;
    public float opacity = 1f;
}

[Serializable]
public class NeuroHubRenderProfile
{
    public string pipeline;
    public int antiAliasing;
    public bool gpuInstancing;
    public bool asyncLoad;
}

[Serializable]
public class NeuroHubStudyManifest
{
    public string schema;
    public string studyId;
    public bool clinicalReviewRequired;
    public NeuroHubModel[] models;
    public NeuroHubRenderProfile renderProfile;
}

public sealed class NeuroHubStudyLoader : MonoBehaviour
{
    [SerializeField] public string studyId = "";
    [SerializeField] private Transform studyRoot;
    [SerializeField] private Material fallbackMaterial;
    [SerializeField] private bool loadOnStart = true;
    private readonly Dictionary<string, GameObject> loaded = new();

    public IReadOnlyDictionary<string, GameObject> LoadedModels => loaded;

    private void Start()
    {
        if (loadOnStart) StartCoroutine(LoadStudy(studyId));
    }

    public IEnumerator LoadStudy(string requestedStudyId)
    {
        ClearStudy();
        if (studyRoot == null) studyRoot = transform;
        string id = string.IsNullOrWhiteSpace(requestedStudyId) ? studyId : requestedStudyId;
        TextAsset manifestAsset = Resources.Load<TextAsset>($"Studies/{id}/study_manifest");
        if (manifestAsset == null)
        {
            Debug.LogError($"NEUROHUB: no existe el manifiesto del estudio: Studies/{id}");
            yield break;
        }

        NeuroHubStudyManifest manifest;
        try { manifest = JsonUtility.FromJson<NeuroHubStudyManifest>(manifestAsset.text); }
        catch (Exception error)
        {
            Debug.LogError($"NEUROHUB: manifiesto inválido: {error.Message}");
            yield break;
        }

        foreach (NeuroHubModel model in manifest.models ?? Array.Empty<NeuroHubModel>())
        {
            // FBX es importado por Unity como asset; el loader busca el prefab
            // generado en Resources para mantener el runtime sin reflexión.
            string resourceKey = $"Studies/{id}/{Path.GetFileNameWithoutExtension(model.file)}";
            ResourceRequest request = Resources.LoadAsync<GameObject>(resourceKey);
            yield return request;
            GameObject prefab = request.asset as GameObject;
            if (prefab == null)
            {
                Debug.LogWarning($"NEUROHUB: {resourceKey} no está en Resources; "
                    + "usa el constructor de escena del Editor para importar FBX.");
                continue;
            }
            GameObject instance = Instantiate(prefab, studyRoot);
            instance.name = model.id;
            ApplyMaterial(instance, model);
            loaded[model.id] = instance;
        }
    }

    public void SetVisible(string modelId, bool visible)
    {
        if (loaded.TryGetValue(modelId, out GameObject model)) model.SetActive(visible);
    }

    public void ClearStudy()
    {
        foreach (GameObject model in loaded.Values)
            if (model != null) Destroy(model);
        loaded.Clear();
    }

    private void ApplyMaterial(GameObject model, NeuroHubModel data)
    {
        foreach (Renderer renderer in model.GetComponentsInChildren<Renderer>(true))
        {
            Material material = fallbackMaterial != null
                ? new Material(fallbackMaterial)
                : new Material(Shader.Find("Universal Render Pipeline/Lit"));
            if (data.color != null && data.color.Length >= 3)
                material.color = new Color(data.color[0], data.color[1], data.color[2],
                    Mathf.Clamp01(data.opacity));
            ConfigureTransparency(material, data.opacity);
            material.enableInstancing = true;
            renderer.sharedMaterial = material;
        }
    }

    private static void ConfigureTransparency(Material material, float opacity)
    {
        if (opacity >= 0.999f) return;
        if (material.HasProperty("_Surface")) material.SetFloat("_Surface", 1f);
        if (material.HasProperty("_Blend")) material.SetFloat("_Blend", 0f);
        if (material.HasProperty("_SrcBlend"))
            material.SetFloat("_SrcBlend", (float)UnityEngine.Rendering.BlendMode.SrcAlpha);
        if (material.HasProperty("_DstBlend"))
            material.SetFloat("_DstBlend", (float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
        if (material.HasProperty("_ZWrite")) material.SetFloat("_ZWrite", 0f);
        material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
        material.EnableKeyword("_ALPHAPREMULTIPLY_ON");
        material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;
    }
}
