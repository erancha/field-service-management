# 0001. Guests on loan-simulator's EC2 instance, one CloudFront distribution per role

- Status: Accepted
- Date: 2026-11-16

## Context

The stack ran only on a workstation under Docker Compose. Google takes a plain-http redirect URI
only for `localhost`, so a hosted stack needs https, and the role apps are told apart by origin: a
sign-in's role comes from the app it completes at, and the session cookie belongs to one host. A
deployment of its own (instance, domain, Route 53, Let's Encrypt) was written but never run.
loan-simulator runs an ARM EC2 instance behind CloudFront from a CloudFormation template every
Docker Compose repo shares, which takes one origin port per stack and admits other stacks as guests.

## Decision

`deploy.sh --ec2` deploys the shared template three times, as guests of loan-simulator's stack:
`field-service-management-tech`, `-app` and `-admin`, one per role, and then runs the one Compose
stack on that instance.

- Each guest stack opens its role's edge port (8001, 8002 or 8003) to CloudFront's servers only
  and adds a distribution of its own, whose `https` address is the role's only way in. TLS ends
  at CloudFront; the hop to the instance is plain HTTP to the nginx edge.
- Each role's Google callbacks, and the worker's photo links, are set from its distribution's
  address, and the session cookie is marked Secure.
- The images are built on the deployer's machine for ARM, the edge's with its configuration and
  the page built in, and loaded into the instance's daemon over SSH, which Compose then runs
  against; the database and the photos live in named volumes.

## Consequences

- No instance, domain or certificate to pay for or renew; the footprint is three ports, three
  distributions and three of the host's four guest slots, and loan-simulator's stack goes first.
- The instance has 2 GB beside loan-simulator's stack, so `docker-compose.ec2.yml` runs one
  replica per role there, and a 1 GB swap file absorbs bursts; locally the replicas stay.
- CloudFront ends a response that sends nothing for 30 seconds: the event stream sends a comment
  every 15 seconds, but a knowledge-base upload or re-index answers only once indexing ends.
- HSTS is not sent, since the edge sees plain HTTP; the disk has no snapshots, and the data moves
  with `tools/sql-helper.sh --backup` and `--restore`.
