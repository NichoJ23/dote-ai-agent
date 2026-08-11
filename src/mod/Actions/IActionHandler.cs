using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Processes a specific type of action command received from the Python agent.
    /// Each handler is responsible for one command verb (e.g., "MOVE_HERO", "OPEN_DOOR").
    /// </summary>
    public interface IActionHandler
    {
        /// <summary>The command verb this handler responds to (e.g., "MOVE_HERO").</summary>
        string CommandType { get; }

        /// <summary>
        /// Validates preconditions before execution.
        /// Returns null if valid, or an error string describing why the action cannot proceed.
        /// </summary>
        string ValidatePreconditions(ActionCommand command);

        /// <summary>Executes the action against game internals. Returns success/failure result.</summary>
        ActionResult Execute(ActionCommand command);
    }
}
