using System.Collections.Generic;

namespace DotEAgent.Models
{
    /// <summary>
    /// Result of an action execution attempt, sent back to the Python agent.
    /// </summary>
    public class ActionResult
    {
        public bool Success;
        public string Error;
        public Dictionary<string, object> Metadata;

        public ActionResult(bool success, string error)
        {
            Success = success;
            Error = error;
        }

        public static ActionResult Ok()
        {
            return new ActionResult(true, null);
        }

        public static ActionResult Ok(Dictionary<string, object> metadata)
        {
            ActionResult r = new ActionResult(true, null);
            r.Metadata = metadata;
            return r;
        }

        public static ActionResult Fail(string error)
        {
            return new ActionResult(false, error);
        }
    }
}
