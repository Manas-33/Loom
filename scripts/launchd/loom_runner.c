/*
 * Launcher for scripts/daily_run.sh, so macOS privacy access (Full Disk Access)
 * can be granted to this one program instead of /bin/bash. It can only run
 * that script. It spawns bash and waits rather than exec'ing it, so it stays
 * the "responsible process" macOS checks for everything the script starts.
 * Rebuilding changes its signature, and the Full Disk Access entry then has
 * to be added again.
 *
 * Build: clang -O2 -o ~/Library/Application\ Support/Loom/loom-runner scripts/launchd/loom_runner.c
 */
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>

extern char **environ;

int main(int argc, char *argv[]) {
    char *args[] = {"/bin/bash", "/Users/dalvi/Documents/loom/scripts/daily_run.sh",
                    argc > 1 ? argv[1] : NULL, NULL};  // at most one flag, e.g. --smoke
    pid_t pid;
    int status;
    if (posix_spawn(&pid, args[0], NULL, NULL, args, environ) != 0) {
        perror("loom-runner: posix_spawn");
        return 127;
    }
    if (waitpid(pid, &status, 0) < 0) {
        perror("loom-runner: waitpid");
        return 127;
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}
