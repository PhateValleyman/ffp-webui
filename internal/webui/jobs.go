package webui

import (
	"errors"
	"strings"
	"sync"
	"time"
)

type Job struct {
	ID        string    `json:"id"`
	Kind      string    `json:"kind"`
	State     string    `json:"state"`
	StartedAt time.Time `json:"started_at"`
	EndedAt   time.Time `json:"ended_at,omitempty"`
	Output    string    `json:"output,omitempty"`
	Error     string    `json:"error,omitempty"`
}

type jobStore struct {
	mu     sync.Mutex
	active bool
	jobs   map[string]Job
	order  []string
}

func newJobStore() *jobStore { return &jobStore{jobs: make(map[string]Job)} }

func (s *jobStore) start(kind string, fn func() (string, error)) (Job, error) {
	s.mu.Lock()
	if s.active {
		s.mu.Unlock()
		return Job{}, errors.New("probíhá jiná administrativní operace; vyčkejte na její dokončení")
	}
	s.active = true
	j := Job{ID: randomID(), Kind: kind, State: "running", StartedAt: time.Now().UTC()}
	s.jobs[j.ID] = j
	s.order = append(s.order, j.ID)
	for len(s.order) > 40 {
		old := s.order[0]
		s.order = s.order[1:]
		if old != j.ID {
			delete(s.jobs, old)
		}
	}
	s.mu.Unlock()
	go func() {
		out, err := fn()
		s.mu.Lock()
		defer s.mu.Unlock()
		j := s.jobs[j.ID]
		j.EndedAt = time.Now().UTC()
		if len(out) > 64<<10 {
			out = out[len(out)-(64<<10):]
		}
		j.Output = strings.TrimSpace(out)
		if err != nil {
			j.State = "failed"
			j.Error = err.Error()
		} else {
			j.State = "completed"
		}
		s.jobs[j.ID] = j
		s.active = false
	}()
	return j, nil
}

func (s *jobStore) get(id string) (Job, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	j, ok := s.jobs[id]
	return j, ok
}
