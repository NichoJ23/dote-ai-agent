namespace DotEAgent.Hooks
{
    /// <summary>
    /// Interface for all game state hook components.
    /// Each hook extracts state from one game subsystem.
    /// </summary>
    public interface IStateHook
    {
        /// <summary>Unique identifier for this hook.</summary>
        string HookId { get; }

        /// <summary>Whether this hook has successfully located its game objects.</summary>
        bool IsBound { get; }

        /// <summary>Attempts to bind to in-game objects. Returns true on success.</summary>
        bool TryBind();

        /// <summary>Extracts current state. Returns null if not bound.</summary>
        object ExtractState();
    }
}
