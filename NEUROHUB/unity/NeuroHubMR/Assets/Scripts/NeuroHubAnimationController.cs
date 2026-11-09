using UnityEngine;

public sealed class NeuroHubAnimationController : MonoBehaviour
{
    [SerializeField] private Animator animator;
    [SerializeField] private string stateName = "NeuroHubPresentation";
    [SerializeField] private bool playOnStart = true;

    private void Awake()
    {
        if (animator == null) animator = GetComponent<Animator>();
    }

    private void Start()
    {
        if (playOnStart) PlayPresentation();
    }

    public void PlayPresentation()
    {
        if (animator == null) return;
        animator.Play(stateName, 0, 0f);
        animator.speed = 1f;
    }

    public void Pause()
    {
        if (animator != null) animator.speed = 0f;
    }

    public void Resume()
    {
        if (animator != null) animator.speed = 1f;
    }

    public void StopAtStart()
    {
        if (animator == null) return;
        animator.speed = 0f;
        animator.Play(stateName, 0, 0f);
    }
}
