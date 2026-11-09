using UnityEngine;
using UnityEngine.InputSystem;

public sealed class NeuroHubGestureController : MonoBehaviour
{
    [SerializeField] private Transform studyRoot;
    [SerializeField] private InputActionProperty pinchSelect;
    [SerializeField] private InputActionProperty rotate;
    [SerializeField] private InputActionProperty scale;
    [SerializeField] private float rotationSpeed = 90f;
    [SerializeField] private float scaleSpeed = 0.8f;
    [SerializeField] private Vector2 scaleLimits = new(0.35f, 3.0f);
    private Vector3 initialScale = Vector3.one;

    private void Awake()
    {
        if (studyRoot == null) studyRoot = transform;
        initialScale = studyRoot.localScale;
    }

    private void OnEnable()
    {
        pinchSelect.action?.Enable();
        rotate.action?.Enable();
        scale.action?.Enable();
    }

    private void OnDisable()
    {
        pinchSelect.action?.Disable();
        rotate.action?.Disable();
        scale.action?.Disable();
    }

    private void Update()
    {
        Vector2 rotation = rotate.action != null ? rotate.action.ReadValue<Vector2>() : Vector2.zero;
        studyRoot.Rotate(Vector3.up, rotation.x * rotationSpeed * Time.unscaledDeltaTime,
            Space.World);
        studyRoot.Rotate(Vector3.right, -rotation.y * rotationSpeed * Time.unscaledDeltaTime,
            Space.Self);

        float zoom = scale.action != null ? scale.action.ReadValue<float>() : 0f;
        float factor = 1f + zoom * scaleSpeed * Time.unscaledDeltaTime;
        float next = Mathf.Clamp(studyRoot.localScale.x * factor,
            initialScale.x * scaleLimits.x, initialScale.x * scaleLimits.y);
        studyRoot.localScale = Vector3.one * next;
    }

    public void ResetTransform()
    {
        studyRoot.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
        studyRoot.localScale = initialScale;
    }
}
