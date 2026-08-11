using System.Collections.Generic;

namespace DotEAgent.Models
{
    /// <summary>
    /// Deserialized action command received from the Python agent over port 5556.
    /// </summary>
    public class ActionCommand
    {
        public string Command;
        public Dictionary<string, object> Parameters;
        public long Timestamp;

        public ActionCommand()
        {
            Parameters = new Dictionary<string, object>();
        }

        /// <summary>Gets a string parameter or null if not present.</summary>
        public string GetString(string key)
        {
            object val;
            if (Parameters.TryGetValue(key, out val) && val != null)
                return val.ToString();
            return null;
        }

        /// <summary>Gets an int parameter or the default value if not present/parseable.</summary>
        public int GetInt(string key, int defaultValue)
        {
            object val;
            if (!Parameters.TryGetValue(key, out val) || val == null)
                return defaultValue;

            if (val is int)
                return (int)val;
            if (val is long)
                return (int)(long)val;
            if (val is double)
                return (int)(double)val;
            if (val is float)
                return (int)(float)val;

            int result;
            if (int.TryParse(val.ToString(), out result))
                return result;
            return defaultValue;
        }

        /// <summary>Gets a float parameter or the default value if not present/parseable.</summary>
        public float GetFloat(string key, float defaultValue)
        {
            object val;
            if (!Parameters.TryGetValue(key, out val) || val == null)
                return defaultValue;

            if (val is float)
                return (float)val;
            if (val is double)
                return (float)(double)val;
            if (val is int)
                return (float)(int)val;
            if (val is long)
                return (float)(long)val;

            float result;
            if (float.TryParse(val.ToString(), out result))
                return result;
            return defaultValue;
        }
    }
}
