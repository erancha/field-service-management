# 0002. The role stacks can host the EC2 instance or join another repo's

- Status: Accepted
- Date: 2026-11-18

## Context

[ADR 0001](0001-guests-on-loan-simulators-ec2-instance.md) made the three role stacks guests of
loan-simulator's stack, and the committed `stack-params.sh` named that host. A person who cloned
this repo without loan-simulator had no such stack, so `deploy.sh --ec2` stopped on a missing host.
Which repos share an instance is a choice of each deployment, not a property of a repo.

## Decision

`EC2_HOST_STACK` moves to the gitignored `params.sh`, blank in `params.example.sh`. Blank, the
technician's stack is a host with an instance of its own and the other two are its guests; set to
another Docker Compose repo's host stack, all three are guests on that stack's instance, as ADR 0001
describes. `stack-params.sh` commits `EC2_INSTANCE_TYPE`, which only a host uses. The rest of ADR
0001 holds.

## Consequences

- The repo deploys alone, and any repo of the group can be the host of the others; a person who
  can afford several instances makes several repos hosts.
- The host goes first, and CloudFormation refuses to delete it while a guest imports its exports.
- Moving the host to another repo starts a new instance with an empty disk: the data comes back
  only from a backup (`tools/sql-helper.sh --backup` and `--restore`).
